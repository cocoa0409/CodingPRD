# Marriage License & Vital Records API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the Marriage License & Vital Records API, the system of record for a county Vital Records office. The office is responsible for an unbroken chain of custody that begins when two prospective spouses file an application and ends, years later, when an apostilled certified copy of their registered marriage travels abroad. Between those endpoints lies a sequence of statutory gates — eligibility screening, a mandatory cooling-off period, a hard license expiration, an officiant's sworn return, record registration, amendment review, and means-tested fee relief — each of which the office is legally obligated to enforce and to be able to reconstruct from an audit trail.

Two concerns dominate the design. The first is **compliance and auditability**: every monetary movement the office makes is recorded in an append-only ledger, and the cash the office reports as collected must always reconcile against the charges it has levied, less the refunds it has paid and the amounts it has waived. The second is **segregation of duties**: the staff member who screens and approves an application must not be the same person who later accepts the officiant's return, and the staff member who adjudicates a fee waiver must not be the one who consumes that waiver against a certified copy. These two principles, woven through the workflows below, are what protect the integrity of the public record and the public purse alike.

The remainder of this document defines the global contract every endpoint honors (Section 2), the business workflows and their rules (Section 3), the endpoint catalogue (Section 4), and the error catalogue (Section 5).

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request to the API must be authenticated through two mandatory HTTP headers. `X-User-ID` identifies the acting user, and `X-User-Role` declares the capacity in which they are acting. If either header is missing, or if `X-User-Role` is not one of the recognized roles, the request is rejected with `ERR_UNAUTHENTICATED`. When the headers are well-formed but the declared role is not permitted to invoke the requested operation, the request is rejected with `ERR_FORBIDDEN`.

The system recognizes exactly five roles: `Applicant`, `Officiant`, `Clerk`, `Registrar`, and `WaiverOfficer`.

Two of these roles are **entity-backed**, meaning the value carried in `X-User-ID` is the identifier of a persisted entity. When `X-User-Role` is `Applicant`, `X-User-ID` is the `id` of the acting `Applicant`; ownership checks on any resource that references an `Applicant` compare that resource's applicant foreign key to `X-User-ID`, so an applicant may act only on applications, licenses, records, copies, amendments, apostilles, and waivers on which they are a party. When `X-User-Role` is `Officiant`, `X-User-ID` is the `id` of the acting `Officiant`; ownership checks on any resource that references an `Officiant` compare that resource's officiant foreign key to `X-User-ID`, so an officiant may file and read only their own returns.

The remaining three roles are **opaque operator identities**. When `X-User-Role` is `Clerk`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server records it where a workflow demands it — for example as `approved_by_user_id` on a `MarriageApplication` it approves or as `issued_by_user_id` on a `CertifiedCopyRequest` it issues — but never compares it to any entity's `id`. When `X-User-Role` is `Registrar`, `X-User-ID` is likewise an opaque operator identifier; the server records it as `accepted_by_user_id` on returns it accepts and as `adjudicated_by_user_id` on amendments it decides, again without equating it to any entity. When `X-User-Role` is `WaiverOfficer`, `X-User-ID` is an opaque operator identifier; the server records it as `adjudicated_by_user_id` on the fee waiver it grants or denies and does not compare it to any entity's `id`. These recorded operator identities are precisely what the segregation-of-duties checks in Section 3 compare against one another.

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

---

### 2.3. Pagination

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, and the accepted range is a minimum of 1 and a maximum of 100. The `offset` parameter is the number of leading items to skip; when omitted it defaults to 0.

Unless a specific endpoint states otherwise, every list endpoint returns its resources sorted by their creation timestamp in ascending order — that is, oldest first.

List responses carry the pagination bookkeeping in the `meta` object of the envelope, exposing `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and Identifiers

Most resources in the system share a common set of system-managed fields. Each such resource carries an `id` (a server-minted UUID with no type prefix), a `created_at` timestamp (ISO 8601 UTC with three fractional digits) recording when the resource was first created, an `updated_at` timestamp in the same format recording the last modification, and a `version` integer that begins at its initial value and increments by one on every mutation of the resource. The `version` field is the basis of the optimistic concurrency mechanism described in Section 2.7.

There is one deliberate exception. The `FeeLedgerEntry` is an append-only audit row: once written it is never modified. A `FeeLedgerEntry` therefore carries only an `id` and a `created_at`; it has neither an `updated_at` nor a `version` field. Every other entity — `Applicant`, `Officiant`, `MarriageApplication`, `MarriageLicense`, `OfficiantReturn`, `MarriageRecord`, `CertifiedCopyRequest`, `AmendmentRequest`, `ApostilleRequest`, and `FeeWaiver` — carries the full quartet of `id`, `created_at`, `updated_at`, and `version`.

Foreign-key references and proposed body values are validated for existence before any business rule runs. When an endpoint path names a resource and the request body also names referenced resources, validation proceeds left to right: the path identifier is resolved first, and only then are the body's foreign keys resolved. The first identifier that does not resolve to an existing resource causes the request to fail with `ERR_NOT_FOUND` before any later reference is examined.

### 2.5. Hierarchical Consistency and Cascading State

Many operations in this system mutate more than one resource. Whenever an operation changes a resource, that resource's `updated_at` is refreshed and its `version` is incremented; this is true of derived-field recomputations as much as of explicit status changes. When a single action cascades across entities, each affected entity independently records its own mutation in this way.

The most important cascades originate from license and record lifecycle events. Accepting an officiant return does not merely move the return forward — it drives the underlying license from `ISSUED` to `USED` and, transitively, brings a new marriage record into existence in the `REGISTERED` state. Expiring a license likewise bubbles upward: when a license moves to `EXPIRED`, the application that produced it also moves to `EXPIRED`. These propagations are described in full where the relevant workflow is narrated in Section 3; the principle here is that the server performs them automatically, without requiring a separate client request against each affected resource, and that each affected resource's `updated_at` and `version` advance accordingly.

### 2.6. Monetary Values, Precision, and Rounding

All money in this system is represented as an integer number of cents; there are no fractional cents and no floating-point currency fields in any stored value or response body. Wherever a fee is computed from a percentage — which occurs only in amendment pricing — each percentage-derived component is rounded to a whole number of cents using the round-half-up convention (a half-cent rounds up) before any components are summed. All other fees are composed entirely of integral constants and therefore require no rounding. The income-to-threshold shortfall ratio used when sizing a waiver is the sole quantity kept as a fractional value, and it is used only for a single comparison, never stored or returned.

### 2.7. Optimistic Concurrency Control

Two specific decisions in this system can rest on a stale view of a parent resource, and both are guarded by optimistic concurrency control on the certified-copy issuance pathway. The decision endpoint that issues or denies a certified-copy request accepts two version-pinning fields in its body: `expected_record_version` and `expected_waiver_version`.

When a certified-copy decision is made, if the client supplies `expected_record_version`, that value must equal the current `version` of the `MarriageRecord` the copy is drawn from. If the record's `version` has advanced since the client last read it — for instance because another writer applied an amendment that bumped the record's `version` and may have changed its seal or confidentiality posture — the decision is rejected with `ERR_STALE_VERSION` (HTTP 412), forcing the client to re-read the record before deciding. Likewise, when a granted waiver is being applied and the client supplies `expected_waiver_version`, that value must equal the current `version` of the `FeeWaiver`; a granted waiver's `version` advances every time it absorbs fees on another issuance, so a decision keyed to a stale waiver view — one that may in fact already be `CONSUMED` — is rejected with `ERR_STALE_VERSION` (HTTP 412) so that the absorption is recomputed against the waiver's current remaining cap.

No other endpoint in the system takes a version-pinning field. Endpoints that are not the certified-copy decision do not accept `expected_record_version` or `expected_waiver_version` and perform no version check.

### 2.8. Segregation of Duties

To prevent a single operator from controlling both sides of a decision, three operations enforce segregation of duties, all surfacing the same `ERR_SEGREGATION_OF_DUTIES` rejection. When a registrar accepts an officiant return, the acting registrar's `X-User-ID` must differ from the `approved_by_user_id` recorded on the application that owns the license. When a clerk issues a certified copy that applies a fee waiver, the acting clerk's `X-User-ID` must differ from the `adjudicated_by_user_id` recorded on that waiver. And when a registrar applies a `SUBSTANTIVE` amendment, the acting registrar's `X-User-ID` must differ from the `approved_by_user_id` of the application underlying the record being amended. These rules are detailed alongside their workflows in Section 3; what unifies them is that an opaque operator identity recorded earlier in a chain disqualifies that same identity from a later, conflicting role in the same chain.

### 2.9. The Append-Only Fee Ledger and Collected-Balance Reconciliation

Every monetary movement the office makes is recorded as a `FeeLedgerEntry`, and the ledger is append-only: entries are written, never edited or deleted, which is why ledger rows lack `updated_at` and `version`. Each entry records the `application_id` of the application chain the movement belongs to, a `kind` that is one of `CHARGE`, `REFUND`, or `WAIVE`, an `amount_cents` holding the positive magnitude of the movement, a `source_entity` naming the entity type that triggered it (one of `LICENSE`, `CERTIFIED_COPY`, `AMENDMENT`, `APOSTILLE`, or `RETURN`), and a `source_entity_id` holding the identifier of that triggering entity.

The three kinds play different roles in the office's books. A `CHARGE` adds money the office has collected; a `REFUND` subtracts money the office returns; a `WAIVE` records revenue the office has forgone and is purely informational with respect to cash. The office's collected balance is therefore the sum of `amount_cents` across all `CHARGE` entries minus the sum of `amount_cents` across all `REFUND` entries, with `WAIVE` entries excluded entirely from that figure. Because the ledger is never filtered or pruned, this collected balance is always equal to the total fees actually charged and not refunded across every entity in the system — the standing invariant the office is required to maintain.

## 3. Business Logic & Workflows

### 3.1. Registering the Parties and the Officiants

Before any marriage can be processed, the people involved must be on file. An applicant is registered with their legal `full_name` and their `date_of_birth`, which must be a date in the past relative to the system clock and which drives every later age computation. Two further attributes shape eligibility: the applicant's `prior_marriage_status`, one of `NEVER_MARRIED`, `DIVORCED`, `WIDOWED`, or `MARRIED` and defaulting to `NEVER_MARRIED`, and `has_judicial_consent`, a boolean defaulting to false that records whether a court has authorized a minor's marriage. When the prior status is `DIVORCED` or `WIDOWED`, the date that prior marriage ended is supplied as `prior_dissolution_date`; otherwise that field is left null.

Officiants are registered separately with their `full_name`, a `credential_type` that is one of `CLERGY`, `JUDGE`, `NOTARY`, or `DEPUTY_COMMISSIONER`, and the date their authority lapses, `registration_expires_on`. A newly registered officiant is `REGISTERED`; a registrar may later move an officiant to `SUSPENDED`, and only a `REGISTERED` officiant may have returns accepted. The officiant's `returns_filed_count` is a derived figure: it is the number of that officiant's returns currently in the `ACCEPTED` state, and it is recomputed and surfaced whenever the officiant is read. A reverse-lookup listing exposes the returns filed by a given officiant.

### 3.2. The Marriage Application and Its Eligibility Screen

A marriage application names its two parties through `applicant_a_id` and `applicant_b_id`, records the `ceremony_county` where the wedding will take place, and carries an `is_confidential` flag (defaulting to false) that determines whether the eventual license and record are private. A freshly created application sits in `DRAFT`. Its `status` field — the lifecycle status carried by every workflow entity in this system — moves through `DRAFT`, `UNDER_REVIEW`, `APPROVED`, `DENIED`, and `EXPIRED`, with `DENIED` and `EXPIRED` being terminal. Two reverse-lookup listings hang off an application: the licenses it has produced and the fee-ledger rows belonging to its chain.

**Submission.** An applicant (or a clerk on their behalf) submits a `DRAFT` application, advancing it from `DRAFT` to `UNDER_REVIEW`. Submission runs three checks. Both `applicant_a_id` and `applicant_b_id` must resolve to existing applicants; the two must not be the same person, or the submission is rejected with `ERR_DUPLICATE_APPLICANT`; and neither party may carry a `prior_marriage_status` of `MARRIED`, or the submission is rejected with `ERR_APPLICANT_ALREADY_MARRIED`.

**The approval decision.** A clerk decides an application that is `UNDER_REVIEW` by supplying a `decision`. When the decision is to approve, the application advances from `UNDER_REVIEW` to `APPROVED`; when it is to deny, it advances from `UNDER_REVIEW` to `DENIED`, recording the supplied or derived `denial_reason_code` while leaving `approved_by_user_id` null and creating neither a license nor a charge. Denial may also be requested explicitly even when the eligibility checks would otherwise pass.

Approval is gated by an eligibility screen applied to each party. **Age:** an applicant's age is the number of whole completed years between their `date_of_birth` and the system clock — the birthday must already have occurred in the current year for that year to count. An applicant at least 18 years old is eligible without consent. An applicant who is at least 16 but not yet 18 is eligible only if `has_judicial_consent` is true; if such an applicant lacks judicial consent the approval is rejected with `ERR_JUDICIAL_CONSENT_REQUIRED`. An applicant younger than 16 is ineligible regardless of consent, and the approval is rejected with `ERR_AGE_INELIGIBLE`. An applicant who turns 18 exactly on the clock date is treated as eligible without consent. **Remarriage waiting period:** for each party whose `prior_marriage_status` is `DIVORCED` or `WIDOWED`, the clock must have reached at least 30 days past their `prior_dissolution_date`; an applicant becomes eligible to remarry on the day exactly 30 days after dissolution and on every day thereafter, and an attempt before that day is rejected with `ERR_REMARRIAGE_WAIT_NOT_MET`. Parties who never married, or who have no recorded dissolution date, skip this check entirely.

On a successful approval the application status becomes `APPROVED`, the acting clerk's `X-User-ID` is stored in `approved_by_user_id`, and the system issues a license, charges the license fee, and recomputes the application's `total_charged_cents` — a figure equal to the sum of `amount_cents` across the `CHARGE` ledger rows attributed to this application chain. The concurrent-license overlap rule that also guards approval is described in Section 3.8 because it shares its interval logic with the officiant double-booking rule.

### 3.3. License Issuance, the Waiting Period, and Expiration

Approval mints a `MarriageLicense`. The license records the `application_id` of the approving application, copies the application's confidentiality into its own `is_confidential` flag, and stamps `issued_at` with the approval instant. From `issued_at` the system derives two boundary instants. The `valid_from` instant is the moment 72 hours after `issued_at`; this is the statutory cooling-off period, expressed in hours. The `expires_at` instant is the moment 90 calendar days after `issued_at`; note that the validity window is measured in days while the cooling-off period is measured in hours. A newly issued license is in status `ISSUED`, and its lifecycle status is one of `ISSUED`, `USED`, `EXPIRED`, or `VOID`. The license issuance also appends a `CHARGE` ledger row for the license fee, which is a flat 9000 cents, with `source_entity` `LICENSE`.

A license becomes valid for ceremonies only at or after `valid_from`: a ceremony whose instant falls strictly before `valid_from` is invalid, while a ceremony exactly at `valid_from` is valid. A license is past its life only strictly after `expires_at`: at the instant exactly equal to `expires_at` the license is not yet expired, but one second after `expires_at` it is. These two boundaries deliberately use opposite inclusivity — the lower bound is inclusive, the upper bound is exclusive of expiry.

**Expiry checking.** A clerk or registrar may evaluate a single license against the clock. If the clock has moved strictly past `expires_at` and no accepted return references the license, the license moves from `ISSUED` to `EXPIRED`, and the owning application bubbles up from `APPROVED` to `EXPIRED`. If the clock has not yet passed `expires_at`, the request is rejected with `ERR_LICENSE_NOT_EXPIRED`. Any return still sitting in `SUBMITTED` against an expiring license is left untouched and remains individually rejectable. The same expiry logic runs as a sweep when the logical clock is advanced (see Section 3.9): every `ISSUED` license past its `expires_at` with no accepted return is expired, and each such license's owning application is expired with it.

**Voiding.** A registrar may void a license that has not been consummated by an accepted return. If any accepted return references the license, the void is rejected with `ERR_LICENSE_ALREADY_USED`. Otherwise the license moves from `ISSUED` to `VOID`, the original license `CHARGE` is reversed by appending a `REFUND` ledger row for the same amount with `source_entity` `LICENSE`, and the application's `total_charged_cents` is recomputed.

### 3.4. The Officiant Return and Record Registration

After the ceremony, the officiant files a return naming the `license_id` the ceremony was performed under, the `officiant_id` who solemnized it, and the `ceremony_date` on which it occurred. A filed return begins in `SUBMITTED`; its status is one of `SUBMITTED`, `ACCEPTED`, or `REJECTED`. At filing time the system computes the return's `filing_deadline`, which is the instant 10 days after `ceremony_date`. Returns are listable filtered by license, and an accepted return's identifier later anchors the marriage record.

Lateness is judged from the moment the return was created: a return is late if its own `created_at` is strictly after its `filing_deadline`. A return created exactly at the deadline is on time and carries no surcharge, while one created a second past the deadline is late. Because lateness is fixed at filing time from `created_at` rather than from the acceptance clock, a return filed on time may be accepted much later without ever becoming late.

**Acceptance.** A registrar accepts a `SUBMITTED` return, advancing it from `SUBMITTED` to `ACCEPTED`. Acceptance enforces a sequence of preconditions. The referenced license must be in `ISSUED`, or the acceptance is rejected with `ERR_LICENSE_NOT_USABLE`. The `ceremony_date` must be at or after the license's `valid_from`, or the acceptance is rejected with `ERR_CEREMONY_BEFORE_VALID`. The `ceremony_date` must be at or before the license's `expires_at`, or the acceptance is rejected with `ERR_CEREMONY_AFTER_EXPIRY`. The referenced officiant must be `REGISTERED`, and the `ceremony_date` must be on or before that officiant's `registration_expires_on`, or the acceptance is rejected with `ERR_OFFICIANT_NOT_AUTHORIZED`. The officiant must not be double-booked, a rule detailed in Section 3.8 and surfaced as `ERR_OFFICIANT_DOUBLE_BOOKED`. Finally, the acting registrar's `X-User-ID` must differ from the `approved_by_user_id` of the application that owns the license, or the acceptance is rejected with `ERR_SEGREGATION_OF_DUTIES`.

On a successful acceptance the return's status becomes `ACCEPTED`, the acting registrar's `X-User-ID` is stored in `accepted_by_user_id`, and three cascades fire. The underlying license moves from `ISSUED` to `USED`. That license transition in turn creates a new `MarriageRecord` in the `REGISTERED` state, copying the license's confidentiality into the record's own `is_confidential` and stamping `registered_at` with the acceptance instant; the record records the `return_id` of the accepted return and the `license_id` of the underlying license. The officiant's `returns_filed_count` is recomputed to reflect the newly accepted return. And if the return was late — that is, if it was filed after its `filing_deadline` — a `CHARGE` ledger row for the late-return surcharge of 2000 cents is appended with `source_entity` `RETURN`, and the application's `total_charged_cents` is recomputed.

**Rejection.** A registrar may instead reject a `SUBMITTED` return, advancing it from `SUBMITTED` to `REJECTED` and recording the supplied `rejection_reason_code`. Rejection leaves the license in `ISSUED`, so a corrected return may be filed later while the license is still valid.

### 3.5. The Marriage Record and Its Lifecycle

A marriage record is the registered, authoritative artifact of the marriage. Its status is one of `REGISTERED`, `AMENDED`, or `SEALED`, with `SEALED` terminal. The record exposes two derived counts that are recomputed on read: `amendment_count`, the number of amendment requests for this record currently in the `APPLIED` state, and `certified_copies_issued`, the number of certified-copy requests for this record currently in the `ISSUED` state. Records are listable filtered by license and by return, and each record offers reverse-lookup listings of its certified-copy requests and of its amendment requests.

A record transitions to `AMENDED` automatically the first time one of its amendments is applied, advancing from `REGISTERED` to `AMENDED`; each further applied amendment leaves an already-`AMENDED` record in `AMENDED` while recomputing `amendment_count`. A record may also be sealed by a registrar. Sealing is permitted from either `REGISTERED` or `SEALED`'s predecessors — that is, from `REGISTERED` or from `AMENDED` — and in both cases is blocked if any certified-copy request for the record is still `PENDING`, in which case the seal is rejected with `ERR_RECORD_HAS_PENDING_COPIES`. A successful seal moves the record to `SEALED` and forces its `is_confidential` to true. Once sealed, the record is locked down: non-governmental copy requests, apostilles, and amendments against it are all refused.

### 3.6. Certified Copies: Access, Pricing, and Waivers

Anyone may request a certified copy of a public record, but confidential records are restricted. A certified-copy request names the `record_id` to copy, a `requester_kind` that is one of `PARTY` (an applicant on the record), `GOVERNMENT` (an agency), or `PUBLIC` (any member of the public), and `copies_requested`, the count of copies wanted, which must be at least 1. An optional `fee_waiver_id` may attach an approved waiver to the request. A new request begins in `PENDING`, and its status is one of `PENDING`, `ISSUED`, `DENIED`, or `REFUNDED`.

**The issuance decision.** A clerk decides a `PENDING` request by supplying a `decision`. A decision to deny advances the request from `PENDING` to `DENIED` and appends no charge. A decision to issue advances it from `PENDING` to `ISSUED` and is the most heavily guarded operation in the system. Its preconditions are evaluated as follows. A sealed record may be copied only for a `GOVERNMENT` requester; any other requester against a `SEALED` record is rejected with `ERR_RECORD_SEALED`. If the record is confidential, the `requester_kind` must be `PARTY` or `GOVERNMENT`; a `PUBLIC` requester against a confidential record is rejected with `ERR_CONFIDENTIAL_ACCESS_DENIED`. If a `fee_waiver_id` is present, the referenced waiver must be in `GRANTED` and its `applicant_id` must be a party of the record, or the issuance is rejected with `ERR_WAIVER_NOT_GRANTED`; and when a waiver is being applied, the acting clerk's `X-User-ID` must differ from that waiver's `adjudicated_by_user_id`, or the issuance is rejected with `ERR_SEGREGATION_OF_DUTIES`. The two version-pinning fields `expected_record_version` and `expected_waiver_version` described in Section 2.7 are also checked on this decision.

On a successful issuance the request's status becomes `ISSUED`, the acting clerk's `X-User-ID` is stored in `issued_by_user_id`, the request's `fee_cents` is computed as described below, a `CHARGE` ledger row for that `fee_cents` is appended with `source_entity` `CERTIFIED_COPY`, and the record's `certified_copies_issued` is recomputed. If a waiver absorbed any portion of the fee, a `WAIVE` ledger row is appended for the absorbed amount, the waiver's `consumed_cents` is increased by that amount, and if `consumed_cents` has reached or exceeded the waiver's `max_waivable_cents` the waiver moves from `GRANTED` to `CONSUMED`.

**Fee computation.** The net `fee_cents` for an issuance is built in a fixed four-step order. First, the gross per-copy total: the first 3 copies are priced at 1500 cents each, and every copy beyond the third is priced at 900 cents each — so the gross is 1500 cents times the lesser of the requested count and 3, plus 900 cents times the count of copies in excess of 3 (zero if 3 or fewer are requested). Second, if the record is confidential, a flat confidential surcharge of 2500 cents is added once to the gross. Third, the government exemption is applied after the surcharge and before any waiver: if the `requester_kind` is `GOVERNMENT`, the gross is set to zero. Fourth, waiver absorption applies only when a granted `fee_waiver_id` is present: the absorbed amount is the lesser of the remaining gross and the waiver's remaining capacity (its `max_waivable_cents` minus its `consumed_cents`), and the final `fee_cents` is the gross minus the absorbed amount. The order is non-negotiable — tier, then surcharge, then government exemption, then waiver — because waiver absorption is measured against the post-surcharge, post-exemption gross.

**Refunds.** A clerk may refund a request that is in `ISSUED`, advancing it from `ISSUED` to `REFUNDED`; a refund attempted on a request in any other state is rejected with `ERR_INVALID_STATE`. A refund appends a `REFUND` ledger row for the request's `fee_cents` with `source_entity` `CERTIFIED_COPY`, and recomputes the record's `certified_copies_issued`. If the original issuance consumed a waiver, the refund reverses that absorption: it appends an offsetting `WAIVE` entry for the negative of the absorbed amount, decreases the waiver's `consumed_cents` by the absorbed amount, and if the waiver had been moved to `CONSUMED` it is restored to `GRANTED`.

### 3.7. Amendments, Apostilles, and Fee Waivers

**Amendments.** A correction to a registered record is filed as an amendment naming the `record_id`, an `amendment_type` that is either `CLERICAL` (a typo fix) or `SUBSTANTIVE` (a change to legal facts that needs registrar sign-off), the `field_path` of the record field being corrected, and the proposed `new_value`. An amendment begins in `SUBMITTED`; its status is one of `SUBMITTED`, `RETURNED_FOR_INFO`, `APPLIED`, or `REJECTED`, with `APPLIED` and `REJECTED` terminal. A registrar decides an amendment by supplying a `decision` that returns it for more information, applies it, or rejects it. Returning advances it from `SUBMITTED` to `RETURNED_FOR_INFO`. The applicant may then resubmit, advancing it from `RETURNED_FOR_INFO` back to `SUBMITTED` and increasing `resubmit_count` by one; resubmission is allowed only while `resubmit_count` is below the limit of 2, and a resubmission attempt at or beyond that limit is rejected with `ERR_RESUBMIT_LIMIT_REACHED`. The `resubmit_count` is the number of times the amendment has cycled back from `RETURNED_FOR_INFO` to `SUBMITTED`.

Applying an amendment advances it from `SUBMITTED` to `APPLIED` and is gated by two preconditions: the record must not be `SEALED`, or the application is rejected with `ERR_RECORD_SEALED`; and if the `amendment_type` is `SUBSTANTIVE`, the acting registrar's `X-User-ID` must differ from the `approved_by_user_id` of the application underlying the record, or the application is rejected with `ERR_SEGREGATION_OF_DUTIES` (a `CLERICAL` amendment carries no such segregation requirement). On a successful application the amendment's status becomes `APPLIED`, the acting registrar's `X-User-ID` is stored in `adjudicated_by_user_id`, a `CHARGE` ledger row for the amendment fee is appended with `source_entity` `AMENDMENT`, the record cascades to `AMENDED`, and `amendment_count` is recomputed. Rejecting an amendment advances it from `SUBMITTED` to `REJECTED`, records the acting registrar in `adjudicated_by_user_id`, and appends no charge.

The amendment fee is computed so that rounding order matters. The base fee is 2000 cents for a `CLERICAL` amendment and 5000 cents for a `SUBSTANTIVE` one. From that base, an expedite component is computed as the base multiplied by 15 percent and rounded half-up to whole cents, and a penalty component is computed as the base multiplied by 10 percent multiplied by the `resubmit_count` and rounded half-up to whole cents. The final fee is the base plus the expedite component plus the penalty component. Each percentage component is rounded to whole cents first and the rounded components are then summed — rounding each separately rather than summing the raw percentages before a single rounding, because the two approaches can differ by a cent.

**Apostilles.** An issued certified copy may be authenticated for foreign use through an apostille request naming the `copy_request_id` to authenticate and the `destination_country` it is bound for. An apostille begins in `REQUESTED`; its status is one of `REQUESTED`, `AUTHENTICATED`, or `REJECTED`. A registrar decides an apostille by supplying a `decision`. Authenticating advances it from `REQUESTED` to `AUTHENTICATED` and is gated by two preconditions: the referenced certified copy must be in `ISSUED`, or the request is rejected with `ERR_COPY_NOT_ISSUED`, and the copy's record must not be `SEALED`, or the request is rejected with `ERR_RECORD_SEALED`. On authentication the apostille's `fee_cents` is set to the flat apostille fee of 4000 cents and a `CHARGE` ledger row for that amount is appended with `source_entity` `APOSTILLE`. Rejecting advances it from `REQUESTED` to `REJECTED` and appends no charge. Apostilles for a given certified copy are listable by reverse lookup.

**Fee waivers.** An indigent party may request a fee waiver naming their `applicant_id`, their self-declared `declared_monthly_income_cents` (which must be at least 0), and their `household_size` (which must be at least 1). A waiver begins in `REQUESTED`; its status is one of `REQUESTED`, `GRANTED`, `DENIED`, or `CONSUMED`, with `DENIED` terminal. A waiver officer decides a `REQUESTED` waiver by supplying a `decision`. The means test rests on a poverty threshold scaled by household size: the threshold is 130000 cents plus 45000 cents for each additional household member beyond the first (so a household of one has a threshold of 130000 cents, a household of two has 175000 cents, and so on). A grant is permitted only when `declared_monthly_income_cents` is at or below that threshold; if income exceeds the threshold the grant is rejected with `ERR_INCOME_ABOVE_THRESHOLD`. Granting advances the waiver from `REQUESTED` to `GRANTED`, stores the acting waiver officer's `X-User-ID` in `adjudicated_by_user_id`, and computes the waiver's `max_waivable_cents`. Denying advances it from `REQUESTED` to `DENIED` and records the adjudicator. Waivers are listable filtered by applicant.

The `max_waivable_cents` cap scales with how far below the threshold the applicant falls. The shortfall ratio is the threshold minus `declared_monthly_income_cents`, divided by the threshold, yielding a value between 0 and 1. If that ratio is at least 0.50 the cap is the full waiver cap of 6000 cents; otherwise it is the partial waiver cap of 3000 cents. The `consumed_cents` field tracks how much of the cap a granted waiver has already absorbed across the copies it has been applied to, and the move to `CONSUMED` occurs when `consumed_cents` reaches `max_waivable_cents`.

### 3.8. Interval Conflicts: Officiant Double-Booking and Concurrent Licenses

Two distinct overlap rules guard this system, and they use deliberately different interval semantics.

The **officiant double-booking** rule guards return acceptance. An officiant may not solemnize two ceremonies whose instants sit within a 60-minute travel buffer of each other. When a return is being accepted, the candidate set is every other `ACCEPTED` return for the same `officiant_id`, excluding the return being accepted. A conflict exists if the absolute difference between this return's `ceremony_date` and any candidate's `ceremony_date` is strictly less than 60 minutes; exactly 60 minutes apart is permitted, so back-to-back ceremonies at the buffer edge are fine. Any single conflict rejects the acceptance with `ERR_OFFICIANT_DOUBLE_BOOKED`.

The **concurrent-license overlap** rule guards application approval, and is evaluated before the license is issued. Neither party may already hold a live license window that overlaps the window the new license would occupy. The prospective new window is the half-open interval running from its `valid_from` (the approval instant plus 72 hours) up to but not including its `expires_at` (the approval instant plus 90 days). The existing windows are taken from every `MarriageLicense` in status `ISSUED` whose application lists the same applicant on either side. Two half-open windows overlap when the new window's `valid_from` is strictly before the existing window's `expires_at` and the existing window's `valid_from` is strictly before the new window's `expires_at`; because the intervals are half-open, touching endpoints do not overlap — an existing window's `expires_at` exactly equal to the new window's `valid_from` is allowed. Each applicant may hold at most one such live window. If approving the application would create an overlapping window for either party, the approval is rejected with `ERR_APPLICANT_LICENSE_OVERLAP`. Note the contrast: the officiant rule treats ceremonies as points guarded by a symmetric buffer with a strict-less-than test, while the license rule treats windows as half-open intervals where touching endpoints are clear.

### 3.9. The Logical Clock and the Expiry Sweep

Because every temporal rule in this system is judged against a system clock, the office exposes two administrative test-driving capabilities. The first sets the logical clock to a supplied absolute instant, given as `to_iso8601`. The second advances the clock to a supplied `to_iso8601` instant and, in the same operation, runs the license-expiry sweep: every license in `ISSUED` whose clock has moved strictly past its `expires_at` with no accepted return is moved to `EXPIRED`, and each such license's owning application is moved to `EXPIRED` in step. These capabilities exist so that waiting periods, expirations, filing deadlines, and remarriage windows can be exercised deterministically.

### 3.10. Validation Ordering

When a single operation could fail several checks at once, the checks are applied in a fixed priority so that the reported error is deterministic. Authentication comes first: a missing or unknown-role header yields `ERR_UNAUTHENTICATED` before anything else. Authorization comes next: a role not permitted for the endpoint yields `ERR_FORBIDDEN`. Then existence: every referenced resource, path identifier before body foreign keys, must resolve, or `ERR_NOT_FOUND` is returned. Then request well-formedness: required fields present, enums valid, and integers in range (`copies_requested` at least 1, `household_size` at least 1, `declared_monthly_income_cents` at least 0), failing which the request is rejected with `ERR_INVALID_REQUEST`. Then, on the certified-copy decision only, the optimistic-concurrency check: when `expected_record_version` or `expected_waiver_version` is supplied it must match the current parent version, or `ERR_STALE_VERSION` is returned. Then the state check: the target must be in a state from which the requested transition is defined, or `ERR_INVALID_STATE` is returned. Only after all of these structural gates pass does the system evaluate the cross-entity, segregation, temporal, eligibility, and fiscal business rules described throughout this section — seal and sealed-record rules, segregation of duties, the time-window and overlap rules, the eligibility and access rules, and the waiver fiscal rules — each surfacing its own specific error code.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource return a `201 Created` status code. Operations that modify or transition an existing resource, and read operations, return a `200 OK` status code. The two clock endpoints return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/applicants` | Register an applicant (party to a marriage) | Clerk, Applicant |
| GET | `/applicants/{id}` | Get an applicant | Clerk, Registrar, Applicant, WaiverOfficer |
| POST | `/officiants` | Register an officiant | Clerk, Registrar |
| GET | `/officiants/{id}` | Get an officiant | Clerk, Registrar, Officiant |
| POST | `/officiants/{id}/suspend` | Suspend an officiant's authority to solemnize | Registrar |
| GET | `/officiants/{id}/returns` | List returns filed by this officiant | Clerk, Registrar, Officiant |
| POST | `/applications` | Create a marriage application in DRAFT | Clerk, Applicant |
| GET | `/applications/{id}` | Get a marriage application | Clerk, Registrar, Applicant |
| GET | `/applications` | List marriage applications; filterable by applicant id | Clerk, Registrar |
| POST | `/applications/{id}/submit` | Submit a DRAFT application for review | Applicant, Clerk |
| POST | `/applications/{id}/decide` | Approve or deny an application under review | Clerk |
| GET | `/applications/{id}/licenses` | List licenses produced by this application | Clerk, Registrar, Applicant |
| GET | `/applications/{id}/ledger` | List fee-ledger rows for this application chain | Clerk, Registrar |
| GET | `/licenses/{id}` | Get a license | Clerk, Registrar, Applicant |
| POST | `/licenses/{id}/expire-check` | Evaluate a license against the clock and expire it if past expiry with no accepted return | Clerk, Registrar |
| POST | `/licenses/{id}/void` | Void an unused license and refund its fee | Registrar |
| POST | `/returns` | File an officiant return after a ceremony (SUBMITTED) | Officiant, Clerk |
| GET | `/returns/{id}` | Get an officiant return | Clerk, Registrar, Officiant |
| GET | `/returns` | List officiant returns; filterable by license id | Clerk, Registrar |
| POST | `/returns/{id}/accept` | Accept a return: mark license USED, register a record | Registrar |
| POST | `/returns/{id}/reject` | Reject a return | Registrar |
| GET | `/records/{id}` | Get a marriage record | Clerk, Registrar, Applicant |
| GET | `/records` | List marriage records; filterable by license id and return id | Clerk, Registrar |
| POST | `/records/{id}/seal` | Seal a record (forces confidential) | Registrar |
| GET | `/records/{id}/certified-copies` | List certified-copy requests for a record | Clerk, Registrar, Applicant |
| GET | `/records/{id}/amendments` | List amendment requests for a record | Clerk, Registrar, Applicant |
| POST | `/certified-copies` | Create a certified-copy request (PENDING) | Clerk, Applicant |
| GET | `/certified-copies` | List certified-copy requests; filterable by record id and fee-waiver id | Clerk, Registrar |
| GET | `/certified-copies/{id}` | Get a certified-copy request | Clerk, Registrar, Applicant |
| POST | `/certified-copies/{id}/decide` | Issue or deny a certified-copy request | Clerk |
| POST | `/certified-copies/{id}/refund` | Refund an issued certified copy | Clerk |
| GET | `/certified-copies/{id}/apostilles` | List apostille requests for a certified copy | Clerk, Registrar, Applicant |
| POST | `/amendments` | Submit an amendment/correction request (SUBMITTED) | Clerk, Applicant |
| GET | `/amendments/{id}` | Get an amendment request | Clerk, Registrar, Applicant |
| POST | `/amendments/{id}/decide` | Apply, return-for-info, or reject an amendment | Registrar |
| POST | `/amendments/{id}/resubmit` | Resubmit an amendment returned for info | Applicant, Clerk |
| POST | `/apostilles` | Request an apostille on an issued certified copy (REQUESTED) | Clerk, Applicant |
| GET | `/apostilles/{id}` | Get an apostille request | Clerk, Registrar, Applicant |
| POST | `/apostilles/{id}/decide` | Authenticate or reject an apostille request | Registrar |
| POST | `/fee-waivers` | Request a fee waiver (REQUESTED) | Clerk, Applicant |
| GET | `/fee-waivers/{id}` | Get a fee waiver | Clerk, Registrar, Applicant, WaiverOfficer |
| GET | `/fee-waivers` | List fee waivers; filterable by applicant id | Clerk, Registrar, WaiverOfficer |
| POST | `/fee-waivers/{id}/decide` | Grant or deny a fee waiver | WaiverOfficer |
| POST | `/_clock/set` | Set the system clock to an absolute instant | Clerk, Registrar |
| POST | `/_clock/advance` | Advance the clock and run the license-expiry sweep | Clerk, Registrar |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_DUPLICATE_APPLICANT` | 409 Conflict |
| `ERR_APPLICANT_ALREADY_MARRIED` | 409 Conflict |
| `ERR_AGE_INELIGIBLE` | 409 Conflict |
| `ERR_JUDICIAL_CONSENT_REQUIRED` | 409 Conflict |
| `ERR_REMARRIAGE_WAIT_NOT_MET` | 409 Conflict |
| `ERR_CEREMONY_BEFORE_VALID` | 409 Conflict |
| `ERR_CEREMONY_AFTER_EXPIRY` | 409 Conflict |
| `ERR_LICENSE_NOT_USABLE` | 409 Conflict |
| `ERR_LICENSE_ALREADY_USED` | 409 Conflict |
| `ERR_LICENSE_NOT_EXPIRED` | 409 Conflict |
| `ERR_OFFICIANT_NOT_AUTHORIZED` | 409 Conflict |
| `ERR_SEGREGATION_OF_DUTIES` | 409 Conflict |
| `ERR_CONFIDENTIAL_ACCESS_DENIED` | 409 Conflict |
| `ERR_RECORD_SEALED` | 409 Conflict |
| `ERR_RECORD_HAS_PENDING_COPIES` | 409 Conflict |
| `ERR_COPY_NOT_ISSUED` | 409 Conflict |
| `ERR_WAIVER_NOT_GRANTED` | 409 Conflict |
| `ERR_INCOME_ABOVE_THRESHOLD` | 409 Conflict |
| `ERR_RESUBMIT_LIMIT_REACHED` | 409 Conflict |
| `ERR_OFFICIANT_DOUBLE_BOOKED` | 409 Conflict |
| `ERR_APPLICANT_LICENSE_OVERLAP` | 409 Conflict |
