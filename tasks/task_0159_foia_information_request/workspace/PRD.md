# Foia Information Request API — Product Requirements Document

## 1. Introduction

The Freedom of Information Act regime obliges federal agencies to balance two opposing duties: maximally disclose government records to the public, and protect the narrow categories of information that statute, executive order, or commercial-confidentiality law place beyond release. In practice this balance is mediated by a process — intake, search, exemption review, fee assessment, third-party consultation, determination, and appeal — whose steps must run in a fixed order, whose deadlines are statutory and whose participants must be kept structurally independent of one another. Most agencies still manage these workflows through email and spreadsheets, which makes it hard to honour the 20-business-day response clock, hard to compute the per-tier fee schedule consistently, and almost impossible to enforce the rule that the officer who issued a denial may not adjudicate the appeal against that same denial.

This document specifies a REST API that captures the entire FOIA lifecycle end-to-end, including the nine statutory exemptions, the three fee tiers (commercial, educational-noncommercial, and public-interest), the Glomar response (neither confirm nor deny), the Reverse-FOIA mechanism that lets a third-party submitter object before their information is released, and the appeal lifecycle with its remand-back-to-search cycle. The system serves five distinct actor types: requesters who file and may appeal; agency officers who run the search and exemption review; an independent appeal authority; third-party submitters; and a test-only clock operator that allows time-gated transitions (deadline expirations, sweep promotions) to be exercised deterministically. Throughout, every state change is captured as an immutable audit entry, so that the agency can demonstrate procedural compliance after the fact.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request to the API (apart from the unauthenticated liveness probe) must carry two headers: `X-User-ID`, a non-empty identifier of the calling principal, and `X-User-Role`, one of the five role names listed below. When either header is missing or empty, the server rejects the call with `ERR_MISSING_AUTH` and HTTP 401. When `X-User-Role` is present but is not one of the five recognised values, the server rejects with `ERR_INVALID_ROLE` and HTTP 401. When the headers are well-formed but the role is not permitted to invoke the requested endpoint, the server rejects with `ERR_FORBIDDEN` and HTTP 403.

The recognised roles are exactly:

- `Requester` — the end user who files a FOIA request and may later appeal its determination.
- `Officer` — the agency FOIA officer responsible for intake, search, exemption claims, fee assessment, and determinations.
- `AppealAuthority` — the senior reviewer who adjudicates appeals, subject to segregation-of-duties from the officer who issued the underlying determination.
- `ThirdParty` — the external submitter whose business information appears in responsive records and who receives a Reverse-FOIA notice.
- `ClockOperator` — a test-driving operator that may advance the server's logical clock and run sweeps; this role exists only to make time-gated transitions reachable from automated tests and has no real-world analogue.

When `X-User-Role` is `Requester`, the value of `X-User-ID` is interpreted as the `id` of the acting `Requester` entity; any ownership check on a resource that references a requester (most notably `Request.requester_id`, and any cascading check via `Request`) compares the resource's foreign-key field to `X-User-ID`. When `X-User-Role` is `Officer`, `AppealAuthority`, `ThirdParty`, or `ClockOperator`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record such an identifier on related entities (for example, the `Appeal.deciding_officer_id` field captures the `X-User-ID` of the appeal authority who accepted the appeal for review, and audit entries capture the calling `actor_id` and `actor_role` as snapshots) but the server does not compare an opaque `X-User-ID` to any entity's `id`.

### 2.2. API Response Structure

#### Standard Success Response Format

All successful API responses (those with 2xx status codes) follow this standard envelope format in their JSON body:

```json
{
  "meta": {
    "api_request_id": "req_RANDOMALPHANUM123456",
    "api_request_timestamp": "2025-05-24T10:30:00.123Z",
    "limit": 10,
    "offset": 0,
    "total_count": 100,
    "has_more": true
  },
  "response_type": "object" | "array",
  "data": { }
}
```

- The `api_request_id` is a server-generated unique identifier for the request that starts with `req_`.
- The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits.
- The `response_type` is either "object" for a single resource or "array" for a list of resources.
- The `data` field contains the resource object or an array of resource objects. For 2xx responses with no data, it contains an empty object. Unless otherwise noted, operations that create or modify a resource will return the created or updated resource object in the data field.
- Pagination-related fields in `meta` (`limit`, `offset`, `total_count`, `has_more`) are included for list endpoints.

#### Standard Error Response Format

All error API responses (4xx status codes) follow this standard envelope format:

```json
{
  "meta": {
    "api_request_id": "req_RANDOMALPHANUM123456",
    "api_request_timestamp": "2025-05-24T10:30:00.123Z"
  },
  "response_type": "error",
  "data": {
    "error_id": "UNIQUE_ERROR_IDENTIFIER_STRING",
    "message": "A human-readable explanation of the error."
  }
}
```

- The `meta` object for error responses contains only `api_request_id` and `api_request_timestamp`.
- The `error_id` is a unique, machine-readable string that identifies the specific error.
- The `message` provides a human-readable explanation of what went wrong.

### 2.3. Pagination

List endpoints accept two optional query parameters, `limit` and `offset`. The `limit` parameter defaults to 10 when omitted, has a minimum of 1, and a maximum of 100; any value outside this range yields `ERR_INVALID_INPUT`. The `offset` parameter defaults to 0 and must be at least 0. List responses are sorted by `created_at` in ascending order, so that the oldest record appears first. The `meta` block on a list response carries `limit`, `offset`, `total_count` (the total number of records matching the filters, ignoring pagination), and `has_more` (true when more records remain after the returned page).

### 2.4. Common Resource Properties, Identifiers, and Versioning

Every persisted resource exposes an `id` field, which is a server-minted UUID without any type-prefix or domain-flavoured affix, and a `created_at` field, which is the ISO 8601 UTC timestamp of creation rendered with three fractional digits. Most resources additionally expose `updated_at`, also ISO 8601 UTC with three fractional digits, and `version`, a monotonically increasing integer starting at 1 that is incremented by exactly one each time the resource is mutated. The two entities `ExemptionClaim` and `AuditEntry` are immutable: once written they are never updated, and consequently they carry only `id` and `created_at` — both `updated_at` and `version` are absent on those two entities.

`Request.id`, `Requester.id`, and similar identifiers are referenced by other entities through foreign-key fields whose values must resolve to an existing resource at the time of insertion. Any cross-entity reference that fails to resolve yields `ERR_FK_NOT_FOUND` with HTTP 404. Path parameters are validated strictly left-to-right: in a path such as that addressing a third-party notice, the notice id is validated for existence and, when nested under a parent path segment, the parent id is checked first. A missing path-parameter resource yields `ERR_NOT_FOUND` with HTTP 404.

### 2.5. Optimistic Concurrency

PATCH operations accept an optional `version` field in the request body. When `version` is supplied and does not match the resource's current `version`, the server rejects the call with `ERR_VERSION_CONFLICT` and HTTP 409 and makes no state change. When `version` is omitted from the body, the optimistic-concurrency check is skipped and the operation proceeds on the current state. Successful mutations always increment `version` by one and refresh `updated_at` to the moment of the write, regardless of whether the call supplied a `version`.

Two specific concurrency races deserve separate treatment because they involve action endpoints rather than PATCH bodies. First, two officers who attempt to issue a final determination on the same request at the same time serialise on the request's status transition out of the determination-pending state: exactly one call succeeds; the other receives `ERR_INVALID_STATE` with HTTP 409. The same `ERR_INVALID_STATE` is returned to the loser when an officer's determination races a requester's withdrawal — exactly one transition out of the in-flight state succeeds, and the other is rejected. Second, a race between a third party's consent and a sweep-driven expiration on the same notice resolves with first-writer-wins on the notice's status; the loser sees `ERR_NOTICE_ALREADY_CLOSED` with HTTP 409, regardless of which direction won.

### 2.6. Audit Trail

Every state transition, every fee event, every third-party response, and every appeal decision appends an immutable `AuditEntry`. Each entry carries a `subject_type` (one of `REQUEST`, `APPEAL`, `THIRD_PARTY_NOTICE`, `FEE_ASSESSMENT`), the `subject_id` of the referenced entity, an `event_code` drawn from a closed enumeration of recognised events (`INTAKE_RECEIVED`, `ACKNOWLEDGED`, `SEARCH_STARTED`, `TOLLING_STARTED`, `TOLLING_ENDED`, `FEE_ESTIMATED`, `FEE_ACCEPTED`, `EXEMPTION_CLAIMED`, `THIRD_PARTY_NOTIFIED`, `THIRD_PARTY_RESPONDED`, `GLOMAR_ISSUED`, `DETERMINATION_ISSUED`, `APPEAL_FILED`, `APPEAL_DECIDED`, `REMANDED`), a snapshot of the calling `actor_role` and `actor_id`, and an open `payload` object capturing the relevant fields of the subject immediately after the event. Audit entries are listable by any combination of `subject_type`, `subject_id`, and `event_code`.

### 2.7. Statutory Deadlines and the Logical Clock

Two statutory windows are core to the FOIA process: the 20-business-day response window on a request (computed from the moment the officer acknowledges the request), and the 10-business-day response window on a third-party Reverse-FOIA notice (computed from the moment the notice is sent). Both windows are computed by walking forward in business days, where a business day is any Monday-through-Friday date that is not on the agency's holiday list. The minimal seeded holiday list contains January 1, July 4, and December 25 of the current calendar year; the implementation may extend this set but must include those three dates at minimum.

Adding `n` business days to a starting datetime works as follows: start with the supplied datetime; count zero business days so far; repeatedly advance the working date by one calendar day, and increment the business-day count by one only when the new date falls Monday through Friday and is not on the holiday list; stop when the count reaches `n`. The starting datetime itself does not count toward the `n` business days — counting begins with the next day. The final result preserves the starting datetime's time-of-day component, and dates are tracked at minute precision.

A response is overdue, but not auto-cancelled, when the current server clock has reached or passed `response_due_at`; the system records this as a soft overdue event in the audit log rather than mutating state automatically. A third-party notice, in contrast, is auto-expired when the clock has reached or passed its `response_deadline` and the notice is still pending: the sweep promotes it to the expired terminal state and emits an audit entry. To make these time-gated transitions reachable from tests, the system exposes a clock-operator capability that advances the server's logical clock to a supplied `to_iso_datetime` and runs the sweep automatically, and a separate sweep capability that runs the same sweep without advancing the clock. Both capabilities are idempotent: running the sweep twice in succession on the same clock produces no additional state changes after the first run.

### 2.8. Segregation of Duties

A core procedural-fairness requirement of FOIA appeals is that the appeal authority who hears an appeal must not be the same person who issued the underlying determination. The server enforces this server-side: when an appeal authority attempts to accept an appeal for review, the server compares `X-User-ID` against the `actor_id` recorded on the `DETERMINATION_ISSUED` audit entry for the underlying request. If they match, the call is rejected with `ERR_SEGREGATION_OF_DUTIES` and HTTP 403, regardless of how syntactically valid the rest of the call is. The same check applies when the appeal authority subsequently issues the decision — the `X-User-ID` issuing the decide call must match the `Appeal.deciding_officer_id` captured at accept-for-review time (so a single appeal authority sees an appeal through from acceptance to decision), and must still not be the original deciding officer.

### 2.9. Fee Tiers, Free Thresholds, and Precision

All monetary values are stored and computed as integer cents — never as floats. Multiplications produce exact integer products. Where the formulas multiply hours by an hourly rate, hours are stored as one-decimal-place values and the per-tier formula spells out exactly which terms accrue; the search-rate-per-hour is forty-five dollars (`SEARCH_RATE_CENTS_PER_HOUR` = 4500 cents), the review-rate-per-hour is sixty dollars and chargeable only on commercial requesters (`REVIEW_RATE_CENTS_PER_HOUR` = 6000 cents), and the per-page copy rate is ten cents (`COPY_RATE_CENTS_PER_PAGE` = 10 cents). Non-commercial tiers receive an allowance of the first 100 pages free (`FREE_PAGES` = 100) and the public-interest tier additionally receives the first two search hours free (`FREE_SEARCH_HOURS` = 2). When the computed subtotal is strictly less than fourteen dollars (`FREE_THRESHOLD_CENTS` = 1400 cents), the agency does not bill at all and the total collapses to zero — this is the statutory de-minimis floor.

A request whose final billable total would otherwise rise sharply from the up-front estimate is protected by a cap that multiplies the original estimate by 1.25; the implementation expresses this cap as an integer-cent computation by multiplying the estimate by 125 and dividing by 100 with truncation toward zero (`FINAL_CAP_MULTIPLIER_TIMES_100` = 125), so that the deterministic order of operations matches the auditor's reference calculation. A free-or-waived request (where the up-front estimate collapsed to zero) is protected against any post-hoc billing: the effective cap for those requests is fourteen dollars minus one cent (1399 cents), one below the free threshold, ensuring such a request can never be billed at finalisation.

### 2.10. Hierarchical Consistency and Cascades

State changes on a request can propagate to its `FeeAssessment` and to its appeals; state changes on an appeal can propagate back to the underlying request. These cascades are described in detail in §3, but two are important enough to call out as system-wide principles. First, when a request transitions from search to determination-pending (closing the search), the linked `FeeAssessment` is finalised: `final_total_cents` is computed from actuals using the final-fee calculation, and the assessment's `status` advances from `ACCEPTED` to `FINALIZED` or from `WAIVED` to `FINALIZED` (a waiver carries through with `final_total_cents` of zero). Second, when an appeal is decided as remanded, the underlying request automatically transitions from its terminal determination state (`DENIED`, `PARTIAL_RELEASE`, or `GLOMAR_ISSUED`) to `REOPENED_BY_APPEAL`; if the appealed determination was Glomar, the cascade also clears `glomar_invoked` back to false and empties `glomar_exemption_basis` so that the agency starts the new search fresh. Every cascade increments the affected resource's `version` by one and refreshes its `updated_at`.

## 3. Business Logic & Workflows

### 3.1. Requester Profile and Tier Justification

Before any FOIA request can be filed, the person filing it must register as a `Requester` with `full_name`, `contact_email`, and `requester_tier`. The legal name is a non-empty string of up to 200 characters, the email is checked for RFC-5322 syntactic validity, and the tier must be one of `COMMERCIAL`, `EDUCATIONAL_NONCOMMERCIAL`, or `PUBLIC_INTEREST`. The non-commercial tiers also require a free-text `tier_justification` of up to 1000 characters explaining why the requester qualifies; for commercial requesters, `tier_justification` may be omitted (it is nullable only on commercial). A registered requester starts with `status` of `ACTIVE`, and only an `ACTIVE` requester can file new requests. The administrative `SUSPENDED` value exists on the requester `status` enum but is reached only through out-of-band agency action.

A requester may amend their own profile — including switching tier — through a versioned update call that accepts an optional `requester_tier`, an optional `tier_justification`, an optional `contact_email`, and the current `version`. When `version` is supplied and does not match, the update is rejected with `ERR_VERSION_CONFLICT`. The same call is also available to an `Officer` so that the agency can correct typos on behalf of a requester.

### 3.2. Filing the Request and Acknowledgement

A requester files a FOIA request by submitting a payload containing their `requester_id`, a `subject_summary` of up to 2000 characters describing what records they want, and optionally `fee_waiver_requested` (a boolean defaulting to false). The server rejects the call if the referenced requester is not in `ACTIVE` status, or if the requester is non-commercial and their `tier_justification` is empty. A newly filed request lands in `INTAKE` status, with `fee_estimate_accepted` defaulting to false, `fee_waiver_granted` initialised to null, `glomar_invoked` defaulting to false, `glomar_exemption_basis` initialised to an empty array, and `tolling_days_consumed` set to zero. An audit entry with `event_code` of `INTAKE_RECEIVED` is appended.

An officer subsequently acknowledges the request, transitioning it from `INTAKE` to `ACKNOWLEDGED`. Acknowledgement sets `filed_at` to the current server time (this is the anchor for the response clock, not the moment the requester originally submitted the form), computes `response_due_at` as 20 business days forward from `filed_at` per the deadline algorithm in §2.7 (`RESPONSE_DAYS` = 20, with zero tolling days consumed at this point), and appends an `ACKNOWLEDGED` audit entry. Acknowledgement is permitted only when the request is currently in `INTAKE`, when the linked requester is `ACTIVE`, and when, for non-commercial tiers, the requester's `tier_justification` is non-empty.

### 3.3. Fee Assessment, Acceptance, and Waiver

After acknowledgement and before search begins, the officer creates a `FeeAssessment` for the request by supplying the `request_id` along with `estimated_pages`, `estimated_search_hours`, and `estimated_review_hours`. Each request may have at most one `FeeAssessment`; a second creation attempt is rejected with `ERR_FEE_ASSESSMENT_EXISTS` and HTTP 409. The assessment starts in `DRAFT`. The officer then computes the up-front estimate, transitioning the assessment from `DRAFT` to `ESTIMATED`; this operation snapshots the requester's tier into `tier_at_assessment` (so that a subsequent tier change does not retroactively re-price the estimate) and computes `estimate_total_cents` as follows.

The estimate computation is performed in four ordered steps. Step one selects the per-tier chargeable quantities. For a commercial requester, the chargeable search hours equal the estimated search hours, the chargeable review hours equal the estimated review hours, and the chargeable pages equal the estimated pages — every unit accrues from the first. For an educational-noncommercial requester, the chargeable search hours are zero (search time is not billable), the chargeable review hours are zero (review time is never billable on any non-commercial tier), and the chargeable pages equal the estimated pages minus 100, floored at zero. For a public-interest requester, the chargeable search hours equal the estimated search hours minus 2, floored at zero, the chargeable review hours are zero, and the chargeable pages equal the estimated pages minus 100, floored at zero. Step two multiplies each chargeable quantity by its per-unit rate using exact integer-cent arithmetic, with no rounding on individual line items: search hours by 4500 cents per hour, review hours by 6000 cents per hour, pages by 10 cents per page. Step three sums the line items into a subtotal in integer cents. Step four applies the free-threshold collapse: if the subtotal in cents is strictly less than 1400, the estimate total is set to zero; otherwise it is set to the subtotal. The order matters — applying the threshold before summing would change which fee components dominate, and is not permitted.

A requester whose estimate has been computed may accept it by issuing an accept action against the assessment; this requires that the calling `X-User-ID` equals the linked `Request.requester_id`. Acceptance advances the assessment from `ESTIMATED` to `ACCEPTED` and sets the request's `fee_estimate_accepted` to true. Separately, when the requester originally indicated `fee_waiver_requested`, the officer may instead waive the fee, transitioning the assessment from `ESTIMATED` to `WAIVED`; the waiver action zeros out `estimate_total_cents`, sets the request's `fee_waiver_granted` to true, and is permitted only when the requester's tier is `EDUCATIONAL_NONCOMMERCIAL` or `PUBLIC_INTEREST`. A waiver request from a commercial requester, or any waiver action invoked against the wrong tier, is rejected with `ERR_WAIVER_NOT_ELIGIBLE` and HTTP 422.

### 3.4. Tolling the Response Clock

An officer who needs more information from the requester (a fee question or a clarification on the subject) may pause the 20-business-day response clock by submitting a tolling-start payload that carries a `reason`. This is a self-loop on the request — its `status` remains `ACKNOWLEDGED`, but an audit entry with `event_code` of `TOLLING_STARTED` is appended to record the pause. Tolling-start is permitted only when the request is currently `ACKNOWLEDGED` and only when the cumulative `tolling_days_consumed` is strictly less than 30 (`MAX_TOLL_DAYS`). The 30-business-day cap is checked before the state precondition, because the cumulative tolling cap is a hard regulatory limit that takes precedence over the lifecycle check; a tolling-start that would push cumulative tolling beyond 30 is rejected with `ERR_TOLLING_LIMIT_EXCEEDED` and HTTP 422.

When the missing information arrives, the officer closes the tolling pause by resuming the clock. Resume-clock is permitted only when an open `TOLLING_STARTED` audit entry exists with no matching `TOLLING_ENDED`. The action computes the number of business days that elapsed during the pause (according to the current logical clock) and adds them to `tolling_days_consumed`, then recomputes `response_due_at` as 20 plus the new `tolling_days_consumed` business days forward from the original `filed_at`. An audit entry with `event_code` of `TOLLING_ENDED` is appended.

### 3.5. Starting Search, the Glomar Branch, and Withdrawal

Once the requester has accepted the estimate (or the fee has been waived, or the estimate was below the free threshold and therefore zero), the officer starts the search by transitioning the request from `ACKNOWLEDGED` to `SEARCH`. The precondition is: either the linked `FeeAssessment` is in `ACCEPTED` or `WAIVED`, or its `estimate_total_cents` is less than or equal to 1400 cents. When neither of these holds — when a `FeeAssessment` exists, its `estimate_total_cents` exceeds 1400, and its `status` is not `ACCEPTED` or `WAIVED` — the start-search call is rejected with `ERR_FEE_NOT_RESOLVED` and HTTP 422. When a waiver was originally requested, the start-search call also requires that `fee_waiver_granted` is no longer null — that is, the waiver question has been adjudicated one way or the other before the search proceeds.

Where the very existence of the records would itself reveal a protected fact, the officer may issue a Glomar response instead of starting a search. A Glomar response is reached as a terminal determination from `DETERMINATION_PENDING`, but procedurally it bypasses search entirely: the request must have `glomar_invoked` set to true, must carry a non-empty `glomar_exemption_basis` array drawn from the closed set `B1`, `B6`, `B7C` (the only exemptions that justify a Glomar), and must have zero `ResponsiveRecord`s associated with it. The issue-glomar action accepts a body containing the `glomar_exemption_basis` array, validates each member against the allowed set (rejecting with `ERR_INVALID_GLOMAR_BASIS` and HTTP 422 if any member is outside `B1`, `B6`, `B7C` or if the array is empty), verifies that no `ResponsiveRecord`s exist (rejecting with `ERR_GLOMAR_WITH_RECORDS` and HTTP 422 if any exist), and on success transitions the request to `GLOMAR_ISSUED`, sets `determination_at` to the current time, and appends a `GLOMAR_ISSUED` audit entry. A consequence of the no-records rule on Glomar is that attempting to create a `ResponsiveRecord` for a request with `glomar_invoked` of true is rejected with `ERR_RECORDS_FORBIDDEN_ON_GLOMAR` and HTTP 422.

A requester may withdraw their own request at any point before determination — from `INTAKE`, `ACKNOWLEDGED`, or `SEARCH` — transitioning it to the terminal `WITHDRAWN` state. The withdrawal action requires that the calling `X-User-ID` matches the request's `requester_id`. When a `FeeAssessment` exists at the time of withdrawal, its status is set to `WAIVED` as a side effect of the withdrawal (so the requester is not subsequently billed for a request they cancelled). An audit entry is appended.

### 3.6. Recording Responsive Records and Claiming Exemptions

During search, the officer logs each responsive record found by submitting a payload containing the `request_id`, a `title` of up to 200 characters, a `page_count` of at least one, and — when the record contains submitter business information — `contains_third_party_info` set to true along with the third party's `third_party_id`. Recording a record is permitted only when the referenced request is currently in `SEARCH` (records cannot be created on a request in any other lifecycle state, and they cannot be created at all on a Glomar request); a record created while marking `contains_third_party_info` true must supply a non-null `third_party_id`. The new record lands with `disposition` of `PENDING_REVIEW`. Records are not automatically tied to third-party notices — the officer must explicitly create the notice in a separate action (see §3.7).

For each record on which an exemption is being asserted, the officer creates an `ExemptionClaim` carrying the `record_id`, the `exemption_code` (one of the nine statutory exemptions `B1`, `B2`, `B3`, `B4`, `B5`, `B6`, `B7`, `B8`, `B9`), the `redaction_scope` (`FULL` to withhold the entire record or `PARTIAL` to redact selectively), and a written `rationale` of up to 1000 characters explaining the claim. Claims are immutable once written — they carry only `id` and `created_at`, no `updated_at` or `version`. The pair `(record_id, exemption_code)` is unique: a duplicate exemption claim on the same record with the same code is rejected with `ERR_DUPLICATE_EXEMPTION` and HTTP 409. Claims may be filed only against a record whose `disposition` is still `PENDING_REVIEW`. Once the exemptions on a record have been reviewed, the officer updates that record's `disposition` to one of `RELEASED_FULL` (no redactions, full release), `RELEASED_REDACTED` (partial redactions applied), or `WITHHELD_FULL` (the entire record withheld) through a versioned disposition update accepting `disposition` and `version`.

### 3.7. Reverse-FOIA Third-Party Notice and Override

When a responsive record discloses third-party submitter information, the officer sends a Reverse-FOIA notice by submitting a payload with the `request_id` and the `record_id`. The notice is created with `status` of `PENDING_RESPONSE`; its `third_party_id` is copied from the linked record (a notice's `third_party_id` must equal the linked record's `third_party_id`), and `response_deadline` is set to ten business days forward from the notice's `created_at` per the deadline algorithm in §2.7 (`THIRD_PARTY_DAYS` = 10). A `THIRD_PARTY_NOTIFIED` audit entry is appended.

The third party then has three available courses of action. They may consent to release, transitioning the notice from `PENDING_RESPONSE` to `CONSENTED`. They may object, supplying non-empty `objection_grounds` and transitioning the notice from `PENDING_RESPONSE` to `OBJECTED`; an officer who subsequently records an exemption claim with `exemption_code` of `B4` against the linked record forces that record's `disposition` to `RELEASED_REDACTED` or `WITHHELD_FULL` rather than `RELEASED_FULL` (the cross-entity link between an objection and a B4 claim is the procedural mechanism through which a third-party objection translates to a redaction). Or they may simply let the deadline pass: when the logical clock advances to or past `response_deadline` and the sweep runs, a still-`PENDING_RESPONSE` notice is transitioned to `EXPIRED`, and the linked record becomes eligible for `RELEASED_FULL` (the third party's silence is treated as non-objection). For both consent and object actions, the calling `X-User-ID` must equal the notice's `third_party_id`, and the action must arrive strictly before the deadline; an action after the deadline (when the current clock has reached or passed `response_deadline`) is rejected with `ERR_THIRD_PARTY_DEADLINE_PASSED` and HTTP 422. Symmetrically, a consent or object on a notice that is already in any terminal state (a race lost to the sweep, or any second-writer scenario) is rejected with `ERR_NOTICE_ALREADY_CLOSED` and HTTP 409.

A separate override path exists for cases where a third party objects but later loses a Reverse-FOIA appeal. The appeal authority may override the notice — transitioning it from either `PENDING_RESPONSE` or `OBJECTED` to `OVERRIDDEN` — when a Reverse-FOIA appeal on the linked record has been dismissed or has been upheld against the third party (specifically, an appeal with `appellant_role` of `THIRD_PARTY` and `status` of `UPHELD` against the third party's grounds, or one with `status` of `DISMISSED`). Override from `PENDING_RESPONSE` to `OVERRIDDEN` is allowed when either dismissed-or-upheld outcome holds; override from `OBJECTED` to `OVERRIDDEN` requires the upheld-against-third-party outcome specifically. After override, the linked record is eligible for any disposition supported by the independent exemption claims on it.

### 3.8. Closing Search and Issuing a Final Determination

The officer closes the search by transitioning the request from `SEARCH` to `DETERMINATION_PENDING`. The precondition is that every responsive record marked with `contains_third_party_info` of true has an associated `ThirdPartyNotice` whose `status` is one of `CONSENTED`, `OBJECTED`, `EXPIRED`, or `OVERRIDDEN` — every third-party submitter has either spoken or been timed out. When this precondition fails (a record with `contains_third_party_info` of true has no notice, or the notice is still pending), the close-search call is rejected with `ERR_MISSING_THIRD_PARTY_NOTICE` and HTTP 422; the same error covers the case where a record is marked third-party but its `third_party_id` is missing. Closing search has two side effects: it recomputes the fee assessment's `final_total_cents` using the final-fee calculation described below, and it advances the assessment's `status` from `ACCEPTED` to `FINALIZED` (or from `WAIVED` to `FINALIZED`, in which case `final_total_cents` is set to zero — a waiver carries through).

The final-fee calculation runs in four ordered steps with the same per-tier formulas as the estimate, but with three crucial differences. First, the input numbers are the actuals: chargeable pages are the sum of `page_count` across responsive records whose `disposition` is in `RELEASED_FULL` or `RELEASED_REDACTED` (records with `disposition` of `WITHHELD_FULL` do not count toward chargeable pages, but records with `RELEASED_REDACTED` count in full — the redaction does not pro-rate). The pages are aggregated in `created_at` ascending order across the request's responsive records, pinned for determinism. Second, the search-hours and review-hours used at finalisation are the values originally captured on the `FeeAssessment` at estimate time (the snapshot of `estimated_search_hours` and `estimated_review_hours`); these are not re-collected at close-search. The tier-specific chargeable-quantity rules from §3.3 apply unchanged to these inputs. Third, a cap rule applies on top of the free-threshold collapse: after the subtotal is summed and the free-threshold collapse is evaluated, the result is capped at the maximum of `estimate_total_cents` and the integer-cent quantity equal to `estimate_total_cents` multiplied by 125 then divided by 100 with truncation toward zero (this expresses a 1.25× cap on growth from the original estimate). When `estimate_total_cents` is zero — a waived request or one that originally fell below the free threshold — the effective cap is 1399 cents (one cent below the free threshold), so that a free-or-waived request can never be billed at finalisation. The cap step runs after the free-threshold step; if the free-threshold step zeroes out the subtotal, the cap step is skipped.

The officer then issues the final determination, which branches on the per-record dispositions. When every responsive record has `disposition` of `RELEASED_FULL`, the request transitions from `DETERMINATION_PENDING` to `RELEASED`; the precondition additionally requires that `glomar_invoked` is false. When at least one responsive record has `disposition` in the set `RELEASED_FULL` or `RELEASED_REDACTED` and at least one other record has `disposition` in the set `RELEASED_REDACTED` or `WITHHELD_FULL` (so the determination is a mix of released and withheld material), the request transitions from `DETERMINATION_PENDING` to `PARTIAL_RELEASE`; again `glomar_invoked` must be false. When every responsive record has `disposition` of `WITHHELD_FULL` and at least one `ExemptionClaim` exists for each such record, the request transitions from `DETERMINATION_PENDING` to `DENIED`; `glomar_invoked` must remain false. All three determination branches set `Request.determination_at` to the current server time and append a `DETERMINATION_ISSUED` audit entry whose payload's `outcome` records which of `RELEASED`, `PARTIAL_RELEASE`, or `DENIED` was chosen. Determination on a non-Glomar request with zero `ResponsiveRecord`s is rejected with `ERR_NO_RESPONSIVE_RECORDS` and HTTP 422.

Beyond the determination branch, the close-search and determine actions also enforce procedural ordering. Close-search requires the request to be in `SEARCH`; determine requires it to be in `DETERMINATION_PENDING`; an action invoked against the wrong state is rejected with `ERR_INVALID_STATE` and HTTP 409.

### 3.9. Appeals, Segregation, and the Remand Cycle

A requester whose request was denied, partially released, or Glomar'd may appeal — and a third-party submitter whose information was released over their objection may file a Reverse-FOIA appeal. The appeal payload carries the `request_id`, the `appellant_role` (`REQUESTER` or `THIRD_PARTY`), and written `grounds` of up to 4000 characters. The referenced request's `status` must be in the set `DENIED`, `PARTIAL_RELEASE`, or `GLOMAR_ISSUED`; an appeal against any other status is rejected with `ERR_INVALID_STATE`. At most one open appeal may exist per `(request_id, appellant_role)` pair where the appeal's `status` is not `DISMISSED` — a second filing in the same pair is rejected with `ERR_DUPLICATE_APPEAL` and HTTP 409. A newly filed appeal lands in `SUBMITTED` with `filed_at` set to the current time, and an `APPEAL_FILED` audit entry is appended.

The appeal authority then accepts the appeal for review, transitioning it from `SUBMITTED` to `UNDER_REVIEW`. The segregation-of-duties check fires here: the calling `X-User-ID` must differ from the `actor_id` recorded on the underlying request's `DETERMINATION_ISSUED` audit entry (or, equivalently, the officer who issued the determination); a same-officer attempt is rejected with `ERR_SEGREGATION_OF_DUTIES` and HTTP 403. On acceptance, the calling `X-User-ID` is captured into `Appeal.deciding_officer_id`, freezing the identity of the adjudicator. The same appeal authority then issues a decision with a request body containing `decision`, transitioning the appeal from `UNDER_REVIEW` to one of three outcomes. A decision of `UPHELD` keeps the original determination in place; the precondition requires only that the appeal is currently `UNDER_REVIEW` and that the calling `X-User-ID` equals `Appeal.deciding_officer_id`. A decision of `REVERSED` (available only when `appellant_role` is `REQUESTER`) reverses the determination — the underlying request's `status` remains as it was (for example, `DENIED`), and the agency must issue a new determination via the remand pathway. A decision of `REMANDED` triggers a cascade: the underlying request, which was in `DENIED`, `PARTIAL_RELEASE`, or `GLOMAR_ISSUED`, automatically transitions to `REOPENED_BY_APPEAL`; on a remand of a Glomar, the cascade also clears `glomar_invoked` to false and empties `glomar_exemption_basis`. The cascade bumps the request's `version` and refreshes `updated_at`. Every decision sets `Appeal.decision_at` to the current time and appends an `APPEAL_DECIDED` audit entry whose payload's `outcome` records the chosen decision.

Once the agency has issued a fresh determination on the reopened request (the request advances out of `REOPENED_BY_APPEAL` into one of the four determination states), the remanded appeal automatically transitions from `REMANDED` to `DISMISSED` — it is no longer the live procedural vehicle, because a new determination is in place. An audit entry is appended on this internal transition. There is also a manual dismissal path for requester appeals filed past the 20-business-day appeal window: when the appeal's `filed_at` plus 20 business days is strictly less than the current clock and the `appellant_role` is `REQUESTER`, the appeal authority may dismiss the appeal directly from `SUBMITTED` (skipping accept-for-review), transitioning it to `DISMISSED`. Conversely, a `decide` call against a requester appeal that arrived past this same 20-business-day window — measured as `Appeal.filed_at` plus 20 business days strictly less than the current clock combined with `appellant_role` of `REQUESTER` — is rejected with `ERR_APPEAL_WINDOW_EXPIRED` and HTTP 422; late requester appeals must be dismissed, not decided.

After a request enters `REOPENED_BY_APPEAL`, the officer reopens search by transitioning the request from `REOPENED_BY_APPEAL` back to `SEARCH`; a `SEARCH_STARTED` audit entry is appended whose payload's `cycle` is set to `post-remand`. The full lifecycle — record collection, exemption review, close-search, determination, and so on — re-runs from that point. Two open-appeal concurrency races deserve mention: two `decide` calls on the same request in `DETERMINATION_PENDING` serialise to one winner on the request's status transition (the loser receives `ERR_INVALID_STATE`); and two `appeal` filings on the same `(request_id, appellant_role)` pair filed concurrently serialise on the unique-open-appeal constraint (the loser receives `ERR_DUPLICATE_APPEAL`).

### 3.10. Validation Ordering and Catch-All Input Checks

Validation on every action runs in a fixed priority order so that the most consequential failures surface first. The ordering, from highest priority to lowest, is: first the auth headers must be present and well-formed (`ERR_MISSING_AUTH`), then `X-User-Role` must be one of the five recognised values (`ERR_INVALID_ROLE`), then the role must be permitted to invoke this endpoint (`ERR_FORBIDDEN`), then path parameters must resolve to existing resources validated left-to-right in the URL (`ERR_NOT_FOUND`), then foreign-key references in the request body must resolve (`ERR_FK_NOT_FOUND`), then the target resource must be in a state from which the requested transition is allowed (`ERR_INVALID_STATE`). After the state check, the business-safety rules apply in the order: segregation-of-duties on appeal acceptance and decision (`ERR_SEGREGATION_OF_DUTIES`), Glomar exemption basis is drawn from `B1`, `B6`, `B7C` only (`ERR_INVALID_GLOMAR_BASIS` against issue-glomar), missing third-party-notice gates on close-search and record creation (`ERR_MISSING_THIRD_PARTY_NOTICE` against close-search and against record creation), the 30-business-day tolling cap (`ERR_TOLLING_LIMIT_EXCEEDED` against start-tolling — note that the cap is checked before the state precondition because cumulative tolling is a hard regulatory cap), the third-party deadline check (`ERR_THIRD_PARTY_DEADLINE_PASSED` against consent and object), the 20-business-day appeal-decision window (`ERR_APPEAL_WINDOW_EXPIRED` against appeal decide), the duplicate-exemption check on `(record_id, exemption_code)` (`ERR_DUPLICATE_EXEMPTION` against exemption-claim create), the no-records-on-Glomar rule (`ERR_RECORDS_FORBIDDEN_ON_GLOMAR` against record create), the fee-waiver eligibility check (`ERR_WAIVER_NOT_ELIGIBLE` against waive), the fee-not-resolved check on start-search (`ERR_FEE_NOT_RESOLVED` against start-search), the no-responsive-records check on determine (`ERR_NO_RESPONSIVE_RECORDS` against determine), the no-records-on-Glomar check on issue-glomar (`ERR_GLOMAR_WITH_RECORDS` against issue-glomar), and finally the optimistic-concurrency check on PATCH endpoints (`ERR_VERSION_CONFLICT`). The catch-all `ERR_INVALID_INPUT` with HTTP 400 fires at the lowest priority when the request body fails its declared schema — missing required field, unknown enum value, wrong type, or numeric value out of range — and serves as the fallback when no more specific business rule applies.

## 4. Endpoint Definitions

New resources created via POST endpoints return HTTP 201 with the created resource. All other successful operations — state-machine actions, modifications via PATCH, GET reads, list endpoints, and the test-driving clock/sweep operations — return HTTP 200. Error responses use the HTTP status codes catalogued in §5. The 4-column summary below names only the URL contract; the request and response payloads, side effects, and preconditions for every endpoint are described in §3.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /foia/requesters | Register a Requester profile. | Requester, Officer |
| GET | /foia/requesters/{id} | Fetch a Requester. | Requester, Officer, AppealAuthority |
| PATCH | /foia/requesters/{id} | Update tier or contact info (requires version). | Requester, Officer |
| POST | /foia/requests | File a FOIA request (initial intake). | Requester |
| GET | /foia/requests/{id} | Fetch a Request with computed fields. | Requester, Officer, AppealAuthority |
| GET | /foia/requests | List requests with filter on status, requester_id. | Officer, AppealAuthority |
| POST | /foia/requests/{id}/acknowledge | Officer acknowledges; sets filed_at and computes response_due_at. | Officer |
| POST | /foia/requests/{id}/start-tolling | Officer pauses the 20-day clock for fee-question/clarification. | Officer |
| POST | /foia/requests/{id}/resume-clock | Officer ends a tolling pause and recomputes response_due_at. | Officer |
| POST | /foia/requests/{id}/start-search | Move ACKNOWLEDGED to SEARCH. | Officer |
| POST | /foia/requests/{id}/close-search | Move SEARCH to DETERMINATION_PENDING; triggers calc_fee_final. | Officer |
| POST | /foia/requests/{id}/determine | Issue final determination — RELEASED, PARTIAL_RELEASE, or DENIED depending on record dispositions. | Officer |
| POST | /foia/requests/{id}/issue-glomar | Issue a Glomar response (neither confirm nor deny). | Officer |
| POST | /foia/requests/{id}/withdraw | Requester withdraws an open request. | Requester |
| POST | /foia/requests/{id}/resume-search | Officer reopens SEARCH after a REMANDED appeal. | Officer |
| POST | /foia/responsive-records | Officer records a responsive record found during search. | Officer |
| GET | /foia/responsive-records/{id} | Fetch a responsive record. | Officer, AppealAuthority |
| PATCH | /foia/responsive-records/{id}/disposition | Officer sets per-record disposition based on ExemptionClaims and ThirdPartyNotice status. | Officer |
| POST | /foia/exemption-claims | Officer claims one of the 9 FOIA exemptions on a record. | Officer |
| GET | /foia/exemption-claims | List exemption claims filtered by record_id or exemption_code. | Officer, AppealAuthority, Requester |
| POST | /foia/third-party-notices | Officer sends a Reverse-FOIA notice to a third party. | Officer |
| POST | /foia/third-party-notices/{id}/consent | Third party consents to release. | ThirdParty |
| POST | /foia/third-party-notices/{id}/object | Third party objects to release. | ThirdParty |
| POST | /foia/third-party-notices/{id}/override | AppealAuthority overrides an objection after the Reverse-FOIA appeal resolves against the third party. | AppealAuthority |
| GET | /foia/third-party-notices/{id} | Fetch a notice. | Officer, AppealAuthority, ThirdParty |
| POST | /foia/appeals | Requester or ThirdParty files an appeal. | Requester, ThirdParty |
| POST | /foia/appeals/{id}/accept-for-review | AppealAuthority accepts the appeal (segregation-of-duties check). | AppealAuthority |
| POST | /foia/appeals/{id}/decide | AppealAuthority decides: UPHELD, REVERSED, or REMANDED. | AppealAuthority |
| POST | /foia/appeals/{id}/dismiss | AppealAuthority dismisses an out-of-window requester appeal. | AppealAuthority |
| GET | /foia/appeals/{id} | Fetch an appeal. | Requester, Officer, AppealAuthority, ThirdParty |
| GET | /foia/appeals | List appeals filtered by status, request_id, appellant_role. | Officer, AppealAuthority |
| POST | /foia/fee-assessments | Officer creates a fee assessment for a Request. | Officer |
| POST | /foia/fee-assessments/{id}/estimate | Compute estimate_total_cents using calc_fee_estimate. | Officer |
| POST | /foia/fee-assessments/{id}/accept | Requester accepts the estimate. | Requester |
| POST | /foia/fee-assessments/{id}/waive | Officer grants a fee waiver. | Officer |
| GET | /foia/fee-assessments/{id} | Fetch a fee assessment. | Officer, Requester |
| GET | /foia/audit-entries | List audit entries filtered by subject_type, subject_id, event_code. | Officer, AppealAuthority |
| POST | /foia/_clock/advance | Test-driving: advance the server's notion of current time. Runs the sweep automatically. | ClockOperator |
| POST | /foia/_sweep/run | Test-driving: idempotently run the sweep without advancing the clock. | ClockOperator |
| GET | /foia/_clock | Test-driving: read current server clock. | ClockOperator, Officer |
| GET | /healthz | Liveness probe (no auth). | (public) |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|---|---|
| ERR_MISSING_AUTH | 401 |
| ERR_INVALID_ROLE | 401 |
| ERR_FORBIDDEN | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_FK_NOT_FOUND | 404 |
| ERR_INVALID_STATE | 409 |
| ERR_VERSION_CONFLICT | 409 |
| ERR_DUPLICATE_APPEAL | 409 |
| ERR_FEE_ASSESSMENT_EXISTS | 409 |
| ERR_NOTICE_ALREADY_CLOSED | 409 |
| ERR_DUPLICATE_EXEMPTION | 409 |
| ERR_SEGREGATION_OF_DUTIES | 403 |
| ERR_INVALID_GLOMAR_BASIS | 422 |
| ERR_MISSING_THIRD_PARTY_NOTICE | 422 |
| ERR_TOLLING_LIMIT_EXCEEDED | 422 |
| ERR_THIRD_PARTY_DEADLINE_PASSED | 422 |
| ERR_APPEAL_WINDOW_EXPIRED | 422 |
| ERR_RECORDS_FORBIDDEN_ON_GLOMAR | 422 |
| ERR_WAIVER_NOT_ELIGIBLE | 422 |
| ERR_FEE_NOT_RESOLVED | 422 |
| ERR_GLOMAR_WITH_RECORDS | 422 |
| ERR_NO_RESPONSIVE_RECORDS | 422 |
| ERR_INVALID_INPUT | 400 |
