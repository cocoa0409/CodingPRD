# Privacy DSAR API — Product Requirements Document

## 1. Introduction

Privacy regulations such as the GDPR and the CCPA grant individuals the right to ask an organization what personal data it holds about them, to demand its deletion, or to opt out of its sale. Every such request — a Data Subject Access Request, or **DSAR** — arrives with a statutory clock already ticking, and the organization (the *data controller*) must verify the requester's identity, discover where the subject's data physically lives across its own systems and those of its downstream vendors, weigh any legal exemptions or litigation holds that may shield specific data, fulfill whatever remains, and notify the vendors who must take action — all before the deadline expires.

This document specifies a REST API that orchestrates that end-to-end lifecycle. The system is multi-tenant: each controller operates independently, registers the data subjects and processors it works with, and owns the requests filed against it. The hard problems the API must solve correctly are the ones a compliance auditor would scrutinize: the deadline arithmetic differs by jurisdiction and bends once (and only once) when an extension is granted; identity verification is a bounded, looping negotiation; the officer who verified a requester's identity may not be the one who later authorizes erasing that person's data; a litigation hold can freeze a deletion mid-flight; and a withdrawal of consent can ripple outward to suppress a subject's marketing records automatically. The remainder of this document defines the global contract every endpoint shares (Section 2), the business logic and state machinery that drive a request from intake to closure (Section 3), the endpoint surface (Section 4), and the catalogue of error identifiers the API may return (Section 5).

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request to the API must carry two headers identifying the caller: `X-User-ID`, an opaque string identifying the individual operator, and `X-User-Role`, naming the operator's role. If either header is absent, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). If both headers are present but the named role is not permitted to perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403). These two checks run before any other validation.

The system recognizes exactly five roles, spelled precisely as follows:

- `IntakeAgent` — the front-desk privacy operator who registers data subjects, intakes requests, and performs identity verification. An `IntakeAgent` cannot decide exemptions or dispatch fulfillment.
- `PrivacyOfficer` — the senior decision-maker who manages controllers, processors, and legal holds, decides exemptions and findings, dispatches fulfillment, and closes requests.
- `FulfillmentWorker` — the operations role that dispatches and completes fulfillment items against downstream processors.
- `ProcessorAgent` — acts on behalf of a downstream processor to acknowledge notifications; it has no write access to the request lifecycle.
- `DataSubjectAgent` — acts on behalf of the data subject to manage that subject's own consent registry entries.

For all five roles, `X-User-ID` is an opaque operator identifier that is **not** tied to any persisted entity; the server never compares it to any entity's `id`. It is, however, recorded where the business logic requires an actor's identity to be remembered: when an `IntakeAgent` verifies a request's identity, the server stores that agent's `X-User-ID` as the request's `verified_by_user_id`, and every audited action records the actor's `X-User-ID` and `X-User-Role` as the `actor_user_id` and `actor_role` of an audit entry. The one place this recorded identity is compared is the segregation-of-duties rule described in Section 3: the `PrivacyOfficer` who dispatches fulfillment must be a different operator (a different `X-User-ID`) than the one pinned in `verified_by_user_id`.

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

All list endpoints accept two query parameters, `limit` and `offset`. The `limit` parameter defaults to 10 when omitted, may be no smaller than 1, and may be no larger than 100. The `offset` parameter defaults to 0 and represents the number of records to skip. List results are always ordered by `created_at` in ascending order, so the oldest matching record appears first; records that share an identical `created_at` (for instance the fulfillment items materialized together by a single dispatch) are further ordered by the sequence in which the server created them, oldest first. For any list response, the `meta` object reports the `limit` and `offset` in effect together with `total_count` (the total number of records matching the query irrespective of pagination) and `has_more` (a boolean that is true when records beyond the current page remain).

### 2.4. Common Resource Properties

Every persisted resource carries a server-minted `id`, which is a UUID with no type prefix and is assigned at creation. Most resources also carry three further system-managed fields: `created_at` and `updated_at`, both ISO 8601 UTC timestamps with three fractional digits, and `version`, an integer. `created_at` is fixed at creation; `updated_at` is refreshed on every mutation; and `version` begins at 1 and increases by exactly 1 on every mutation of that resource, including mutations that occur as a side effect of an operation on another resource.

Two resource types are exceptions. An audit entry and the system clock are append-only or singleton records that carry only `id` and `created_at`; they have neither an `updated_at` nor a `version`, because they are never updated in place. Wherever this document refers to a resource's `version` being incremented or its `updated_at` being refreshed, those statements do not apply to audit entries.

### 2.5. Nested Resource Retrieval

Several resources are addressed beneath a parent in the URL — for example, the findings, exemptions, fulfillment items, and audit entries of a particular request, or the notifications of a particular fulfillment item. When such a nested path is used, the server validates the chain left to right: the parent resource named earlier in the path must exist before the child is resolved. If any referenced resource in the path or request body does not exist, the request fails with `ERR_NOT_FOUND` (HTTP 404). Existence is checked in the natural left-to-right order — controller, then request, then finding, item, processor, or exemption — so the first broken link in the chain is the one reported.

### 2.6. Jurisdiction, Deadlines, and the Statutory Clock

A request's statutory deadline is governed by the jurisdiction of its owning controller, which is fixed at one of two values, `GDPR` or `CCPA`, when the controller is registered. A controller under `GDPR` must answer within 30 calendar days; a controller under `CCPA` within 45 calendar days. The deadline is anchored to the `received_at` instant supplied at intake and is recorded on the request as `deadline_at`. The precise arithmetic, including how a granted extension stretches the window, is given in Section 3.

The system maintains its own notion of the current moment so that deadline behavior is deterministic and testable. The clock's value is exposed as `current_utc`. By default it tracks real wall-clock time, but it can be set explicitly to a supplied instant. This clock is the single source of every server-stamped domain timestamp: a resource's `created_at` and `updated_at`, a consent's `withdrawn_at`, a notification's `dispatched_at` and `ack_deadline_at`, and an audit entry's `created_at` are all taken from `current_utc` at the moment of the operation. The lone exception is the response envelope's `api_request_timestamp` (Section 2.2), which is stamped from real wall-clock time and is therefore unaffected by an explicitly set clock. Setting the clock is also the event that drives two background sweeps: any non-terminal request whose deadline has now passed is expired, and any sent-but-unacknowledged processor notification whose acknowledgement window has now passed is marked overdue. These sweeps are detailed in Section 3.

All time arithmetic in this system is exact. Deadline computation works in whole calendar days added to the `received_at` instant, preserving its time-of-day; the processor acknowledgement window is exact hour arithmetic on a UTC instant. Neither involves rounding.

### 2.7. Numeric Precision

Two computed quantities are percentages and are reported as numbers with two decimal places, rounded half up. The first is a request's `fulfillment_progress_pct`; the second is the `erasure_exposure_score` returned by the erasure-risk read. In both cases the division is performed first on integer inputs and a single rounding is applied to the final percentage — never per item. A computed business-days countdown, `business_days_remaining`, is by contrast an integer count and is never negative.

### 2.8. Optimistic Concurrency Control

Two write operations are guarded against acting on a stale view of their target, and both use the same mechanism: the client must submit the `version` it last observed, and the server rejects the write if that value no longer matches the target's current `version`.

When dispatching fulfillment for a request, the caller must include `expected_request_version` carrying the `version` of the request as the client last read it. Between that read and this dispatch, an exemption decision or a finding confirmation may legitimately have advanced the request's `version`; if so, the client's picture of which findings and exemptions are in play is stale, and the dispatch is rejected with `ERR_STALE_VERSION` (HTTP 412) rather than fanning out fulfillment items from an outdated view. Likewise, when dispatching an individual fulfillment item, the caller must include `expected_item_version` carrying the item's last-observed `version`; if a prior unblock has advanced the item's `version` since the client read it, the dispatch is rejected with `ERR_STALE_VERSION` (HTTP 412). Operations not named here do not take a version field.

### 2.9. Request-Body Integrity

On any endpoint that accepts a body, the server validates that required fields are present and well-typed, that any enum-valued field carries a member of its declared set, and that a finding's `record_count` is at least 1. A violation of any of these is reported as `ERR_INVALID_REQUEST` (HTTP 400).

## 3. Business Logic & Workflows

### 3.1. Establishing the Compliance Registry

Before any request can be handled, a `PrivacyOfficer` registers the controller that will answer it. Registration supplies the controller's legal `name`, its `jurisdiction`, and a `dpo_email` for its Data Protection Officer; the controller begins life with an `open_request_count` of 0. That count is a live measure of workload: it reflects the number of requests this controller owns whose status is anything other than the three closed states. Whenever a request reaches `CLOSED_FULFILLED`, `CLOSED_REJECTED`, or `CLOSED_EXPIRED`, the count is recomputed downward; whenever a new request is intaken, it rises.

Around each controller, several registries are populated. A data subject is registered — typically by an `IntakeAgent`, though a `PrivacyOfficer` may also do so — under a controller identified by `controller_id`, and carries the subject's `email` (the primary key used to match the person across systems), `full_name`, a `jurisdiction_residency` of `EU`, `CALIFORNIA`, or `OTHER` (the residency that grants the privacy right), and an optional operator-declared `known_record_count` used to size the discovery effort; when supplied it must be an integer no smaller than 0 (a negative value is rejected with `ERR_INVALID_REQUEST`), and when omitted, `known_record_count` defaults to 0. A processor — a downstream sub-vendor — is registered by a `PrivacyOfficer` with its owning `controller_id`, a `name`, a `notify_email` to which downstream notifications are sent, and an optional `sla_ack_hours` stating how many hours the processor is contractually allowed to acknowledge a notification; `sla_ack_hours` must be at least 1 and defaults to 72 when omitted. A processor's `status` begins `ACTIVE` and may be moved to `SUSPENDED`; a `SUSPENDED` processor cannot receive new notifications. Suspension is a `PrivacyOfficer` action that transitions `status` from `ACTIVE` to `SUSPENDED`.

The consent registry records, per subject and `purpose`, whether the subject currently permits a kind of processing. A consent grant is created with a `data_subject_id` and a `purpose` of `MARKETING`, `ANALYTICS`, `SALE_OF_DATA`, or `ESSENTIAL`; its `state` begins `GRANTED` and its `withdrawn_at` is null while granted. A `DataSubjectAgent` (or a `PrivacyOfficer` acting on the subject's behalf) may withdraw a consent that is currently `GRANTED`, flipping its `state` to `WITHDRAWN` and stamping `withdrawn_at` with the current clock instant. Finally, a `PrivacyOfficer` may place a legal hold to freeze a subject's data against deletion: a hold names the placing `controller_id`, the affected `data_subject_id`, a `matter_reference` justifying it, and a non-empty `data_categories` set drawn from `IDENTITY`, `FINANCIAL`, `BEHAVIORAL`, `CONTACT`, and `HEALTH`. A hold's `state` begins `ACTIVE`; only an `ACTIVE` hold blocks deletion. Lifting a hold by a `PrivacyOfficer` moves its `state` from `ACTIVE` to `LIFTED`.

### 3.2. Intake and the Identity-Verification Loop

A new DSAR is intaken by an `IntakeAgent` or `PrivacyOfficer` against a controller and subject, naming `controller_id`, `data_subject_id`, the `request_type` (one of `ACCESS`, `DELETION`, or `OPT_OUT`, fixed permanently at intake), and the `received_at` instant the request was received. On creation the request enters `PENDING_VERIFICATION`, its `deadline_at` is computed (Section 3.3), and the owning controller's `open_request_count` rises by one. The request also tracks `identity_attempts` (starting at 0), `extension_count` (starting at 0), and `version` (starting at 1).

Identity verification is a bounded loop conducted by an `IntakeAgent`. From `PENDING_VERIFICATION`, the agent either accepts the evidence — supplying an `evidence_reference` — or rejects it — supplying a `reason`. Accepting requires that the request currently be in `PENDING_VERIFICATION` and that the request not be past its deadline (if the clock has passed `deadline_at`, the action is refused with `ERR_DEADLINE_PASSED`); it advances the request `PENDING_VERIFICATION → DISCOVERY`, increments `identity_attempts` by one, pins the acting agent's identity into `verified_by_user_id`, appends an audit entry of type `IDENTITY_VERIFIED`, and bumps `version`. Rejecting requires only that the request be in `PENDING_VERIFICATION`; it advances `PENDING_VERIFICATION → VERIFICATION_REJECTED`, increments `identity_attempts` by one, appends an `IDENTITY_REJECTED` audit entry, and bumps `version`.

From `VERIFICATION_REJECTED`, the subject may try again: an `IntakeAgent` resubmits, which requires the request to be in `VERIFICATION_REJECTED` and that `identity_attempts` be fewer than 3. If three attempts have already been recorded, resubmission is refused with `ERR_VERIFICATION_ATTEMPTS_EXHAUSTED` and the request can only be closed. A successful resubmission returns the request `VERIFICATION_REJECTED → PENDING_VERIFICATION` and bumps `version`, re-opening the loop. Alternatively a `PrivacyOfficer` may close a rejected request from `VERIFICATION_REJECTED → CLOSED_REJECTED`, which appends a `REQUEST_CLOSED` audit entry, recomputes the controller's `open_request_count` downward, and bumps `version`. Both the verify path (where it records the acting agent's `X-User-ID` into `verified_by_user_id`) and the reject path append their respective audit entries through the same audit log that records the actor's role and id and a human-readable `detail`.

### 3.3. Deadline Computation and the Single Extension

A request's `deadline_at` is its `received_at` instant plus a whole number of calendar days, with the time-of-day of `received_at` preserved. The number of base days is set by the controller's jurisdiction: 30 calendar days under `GDPR`, 45 calendar days under `CCPA`. While `extension_count` is 0, that base figure is the entire window. The deadline is recomputed only when an extension is granted.

Exactly one extension is permitted per request, and only before fulfillment is dispatched — that is, while the request is in `DISCOVERY` or `UNDER_REVIEW`. A `PrivacyOfficer` grants it (supplying a `reason`), provided `extension_count` is 0; a second attempt, when `extension_count` is already 1, is refused with `ERR_EXTENSION_LIMIT_REACHED`. Both jurisdictions permit an extension. Granting raises `extension_count` to 1, recomputes `deadline_at`, appends a `DEADLINE_EXTENDED` audit entry, and bumps `version`; the request remains in the state it was in (the extension does not itself change status). When the single extension is in effect, the window becomes the base figure plus a jurisdiction-specific extension allowance: a `GDPR` controller adds a further 60 calendar days (yielding 30 plus 60), while a `CCPA` controller adds a further 45 calendar days (yielding 45 plus 45). In every case the recomputed `deadline_at` is the `received_at` instant plus the total calendar-day figure, still preserving its time-of-day.

On any read of a request, the system reports `business_days_remaining`: a count of business days, Monday through Friday in UTC, lying strictly after the current clock date and up to and including the deadline date. Concretely, the start day — the calendar date of `current_utc` — is excluded, and the deadline date is included if it is itself a weekday; the count walks each date from the day after the current date through the deadline date inclusive, adding one for every date that falls on a weekday and treating Saturday and Sunday as non-counting. If the deadline lies before the current moment, the result is 0 rather than a negative number.

### 3.4. Cross-System Discovery and Finding Resolution

Once verified, a request sits in `DISCOVERY`, the phase in which operators record where the subject's data was actually found. A `PrivacyOfficer` or `IntakeAgent` records a finding against the request, naming the `processor_id` of the system in which data was located, the `data_category` (`IDENTITY`, `FINANCIAL`, `BEHAVIORAL`, `CONTACT`, or `HEALTH`), the `record_count` located (which must be at least 1), and the match `confidence`, either `EXACT` or `PROBABLE` — `PROBABLE` matches are tentative and need confirmation before they can be fulfilled. Recording a finding is permitted only while the parent request is in `DISCOVERY`; an attempt against a request in any other state is refused with `ERR_INVALID_STATE`. A new finding begins in `PENDING`, is bound to its parent request through that request's identifier (its `dsar_request_id`), raises the request's `discovery_finding_count`, and bumps the request's `version`; recording a finding does not itself append an audit entry (the `DISCOVERY_RECORDED` event type is a valid audit-filter value but is not emitted by this system). The `discovery_finding_count` is reported as a live count of the findings bound to the request rather than a separately stored counter. The same `dsar_request_id` linkage carries through to the request's exemptions, fulfillment items, and audit entries, and is available as a filter when those collections are listed.

Each finding must be resolved by a `PrivacyOfficer` before discovery can close, and resolution may only happen while the parent request is in `DISCOVERY`. A `PENDING` finding may be confirmed (`PENDING → CONFIRMED`) or dismissed (`PENDING → DISMISSED`); a finding already `CONFIRMED` may still be dismissed (`CONFIRMED → DISMISSED`) so long as the request remains in `DISCOVERY`, but never reconfirmed. Any of these decisions on a finding bumps the parent request's `version`; attempting a finding decision when the finding is not in the required state, or when its parent request has already left `DISCOVERY`, is refused with `ERR_INVALID_STATE`.

Closing discovery is a `PrivacyOfficer` action that advances the request `DISCOVERY → UNDER_REVIEW`. It is permitted only when the request is in `DISCOVERY`, when at least one finding exists (an attempt with zero findings is refused with `ERR_NO_FINDINGS`), and when no finding remains `PENDING` — every finding must be either `CONFIRMED` or `DISMISSED`, or the action is refused with `ERR_UNRESOLVED_FINDINGS`. Like the verify and dispatch actions, completing discovery is also gated by the deadline: it is one of the actions refused with `ERR_DEADLINE_PASSED` if attempted past `deadline_at`. Completing discovery bumps the request's `version`.

### 3.5. Exemptions, Legal Holds, and the Fulfillment Fan-Out

While a request is in `DISCOVERY` or `UNDER_REVIEW`, a `PrivacyOfficer` may assert an exemption claiming that a category of data should be shielded from fulfillment, naming the `data_category` it covers and the legal `basis` — `LEGAL_OBLIGATION`, `FREEDOM_OF_EXPRESSION`, `LEGAL_HOLD`, or `TRADE_SECRET`. An asserted exemption begins in `ASSERTED` and bumps the request's `version`. Every exemption must be decided by a `PrivacyOfficer` while the request is in `UNDER_REVIEW`: the officer supplies a `decision` selecting the outcome, which moves the claim `ASSERTED → UPHELD` or `ASSERTED → OVERRULED`, appends an `EXEMPTION_DECIDED` audit entry, and bumps the request's `version`. Only an `UPHELD` exemption actually shields its category. A decision attempted when the claim is not `ASSERTED`, or when the request is not in `UNDER_REVIEW`, is refused with `ERR_INVALID_STATE`. There is one further guard, symmetric across the two outcomes only in its precondition: when the `basis` is `LEGAL_HOLD`, upholding the claim requires that an `ACTIVE` legal hold actually exist on the subject covering the same `data_category`; if no such hold backs it, the decision is refused with `ERR_EXEMPTION_BASIS_UNSUPPORTED`. Overruling carries no such backing requirement.

Dispatching fulfillment is the pivotal `PrivacyOfficer` action that advances the request `UNDER_REVIEW → FULFILLING` and materializes the work to be done. It carries `expected_request_version` and is subject to the optimistic-concurrency check of Section 2.8. Three preconditions are evaluated for this action, and they constitute the request's most consequential gate. First, the request must be in `UNDER_REVIEW`. Second, the acting `PrivacyOfficer` must not be the operator pinned in `verified_by_user_id` — the segregation-of-duties rule, under which dispatching with the same `X-User-ID` that verified identity is refused with `ERR_SEGREGATION_OF_DUTIES`. Third, every exemption on the request must already be decided — none may still be `ASSERTED`, or the dispatch is refused with `ERR_UNDECIDED_EXEMPTION`. Dispatch is also among the deadline-gated actions, refused with `ERR_DEADLINE_PASSED` past the deadline.

When dispatch proceeds, the system fans out one fulfillment item per `CONFIRMED` finding, deriving each item from its finding. An item records the originating `discovery_finding_id`, mirrors the finding's `processor_id`, `data_category`, and `record_count`, and takes an `action` derived from the request's `request_type`: an `ACCESS` request produces `DISCLOSE` items, a `DELETION` request produces `ERASE` items, and an `OPT_OUT` request produces `SUPPRESS` items. The state each item is born into depends on the exemption and legal-hold picture. A finding whose `data_category` is shielded by an `UPHELD` exemption produces an item created directly in `SKIPPED_EXEMPT`. A finding whose category is **not** so shielded normally produces a `QUEUED` item — but with one exception specific to deletions: for a `DELETION` request, an `ERASE` item whose `data_category` is frozen by an `ACTIVE` legal hold on the subject is created in `BLOCKED` rather than `QUEUED`. Items that are neither exempt nor frozen are created in `QUEUED`. Dispatch appends a `FULFILLMENT_DISPATCHED` audit entry and bumps the request's `version`.

A `BLOCKED` item is not abandoned: once the legal hold over its category has been lifted, a `PrivacyOfficer` may unblock it, returning it `BLOCKED → QUEUED`. Unblocking is permitted only when the item is `BLOCKED` and no `ACTIVE` legal hold any longer covers the item's `data_category`; if such a hold is still active, the unblock is refused with `ERR_LEGAL_HOLD_ACTIVE`. A successful unblock bumps the item's `version` — which is precisely why a later dispatch that still carries the pre-unblock `expected_item_version` will be caught by the stale-version check.

### 3.6. Dispatching Items, Notifying Processors, and Completing Work

A `QUEUED` fulfillment item is dispatched to its processor by a `FulfillmentWorker`, advancing it `QUEUED → DISPATCHED`. The dispatch carries `expected_item_version` and is OCC-guarded per Section 2.8. It requires that the item be `QUEUED`, that the parent request be in `FULFILLING`, and that the referenced processor be `ACTIVE` — dispatching to a `SUSPENDED` processor is refused with `ERR_PROCESSOR_SUSPENDED`. A successful dispatch creates a processor notification for this item's processor, born in `SENT` with its `dispatched_at` stamped to the current clock instant, appends a `FULFILLMENT_DISPATCHED` audit entry, and bumps the item's `version`.

Each notification records the originating `fulfillment_item_id` and the `processor_id` being notified, and computes an `ack_deadline_at` equal to its `dispatched_at` plus the processor's `sla_ack_hours` hours of exact UTC-instant arithmetic. A notification begins in `SENT`. A `ProcessorAgent` acknowledges it, moving it to `ACKNOWLEDGED`; acknowledgement is allowed whether the notification is still `SENT` or has already gone `OVERDUE`. A notification goes `OVERDUE` only by the clock sweep: when the clock is set forward past a notification's `ack_deadline_at` while it is still `SENT`, the sweep marks it `OVERDUE`. (Acknowledgement of an already-overdue notification is still honored.)

Completing a fulfillment item is a `FulfillmentWorker` action that advances it `DISPATCHED → COMPLETED`. It requires the item to be `DISPATCHED` and the item's notification to have reached `ACKNOWLEDGED`; completing an item whose notification is not yet acknowledged is refused with `ERR_NOTIFICATION_NOT_ACKED`. Completion bumps the item's `version`. Completion also carries one cascade, and only for suppression work: when a completed item's `action` is `SUPPRESS`, every consent record of the subject whose `purpose` is `MARKETING`, `ANALYTICS`, or `SALE_OF_DATA` and whose `state` is still `GRANTED` is flipped to `WITHDRAWN` with its `withdrawn_at` stamped to the current clock instant. Consent records for the `ESSENTIAL` purpose are never swept by this cascade.

### 3.7. Progress, Erasure Risk, and Closing the Request

At any point, a read of a request reports `fulfillment_progress_pct`, the share of its fulfillment items that have reached a terminal state. When the request has no fulfillment items, this figure is 0.00. Otherwise it is one hundred multiplied by the number of items in `COMPLETED` or `SKIPPED_EXEMPT`, divided by the total number of items, with the division performed first and the resulting percentage rounded half up to two decimal places.

For deletion requests, a dedicated erasure-risk read reports how much weighted exposure a request still carries. The read is permitted on a request of any `request_type` and is never refused on the basis of type; for a request that has no `ERASE` items — including any non-`DELETION` request, whose items are never `ERASE` — it simply yields a residual of 0, a total of 0, and a score of 0.00. Each data category has a sensitivity weight: `HEALTH` is 5, `FINANCIAL` is 4, `IDENTITY` is 3, `CONTACT` is 2, and `BEHAVIORAL` is 1. The read considers only the request's `ERASE` items. The residual figure sums, over every `ERASE` item whose state is `QUEUED`, `DISPATCHED`, `BLOCKED`, or `SKIPPED_EXEMPT`, that item's category weight multiplied by its `record_count`; an item that has reached `COMPLETED` is fully remediated and contributes nothing to residual. The total figure sums the same weighted product over all `ERASE` items regardless of state. The `erasure_exposure_score` is then one hundred multiplied by the residual divided by the total — with the weighted sums accumulated in integer space, the division performed first, and a single half-up rounding to two decimal places applied to the percentage. When the total is 0 (the request has no `ERASE` items at all), the score is 0.00. The read also returns the two underlying integers, `residual_weighted` and `total_weighted`.

A request is finalized by a `PrivacyOfficer`, who supplies a `disposition`. From `FULFILLING`, closing advances the request `FULFILLING → CLOSED_FULFILLED`, but only when no fulfillment item remains in `QUEUED`, `DISPATCHED`, or `BLOCKED` — every item must have reached `COMPLETED` or `SKIPPED_EXEMPT`, or the close is refused with `ERR_FULFILLMENT_INCOMPLETE`. From `VERIFICATION_REJECTED`, the same close action advances the request `VERIFICATION_REJECTED → CLOSED_REJECTED`. Either closure appends a `REQUEST_CLOSED` audit entry, recomputes the owning controller's `open_request_count` downward, and bumps the request's `version`.

### 3.8. The Deadline Clock and Expiry Sweep

The system clock can be advanced explicitly by a `PrivacyOfficer`, who supplies the new instant as `to_iso8601`. The action returns 200 with a `data` object carrying exactly one field, the updated `current_utc` (the clock is not serialized with `id`, `created_at`, or any other field). Setting `current_utc` to that value drives two sweeps in addition to updating the clock. First, every non-terminal request — one whose status is any of `PENDING_VERIFICATION`, `VERIFICATION_REJECTED`, `DISCOVERY`, `UNDER_REVIEW`, or `FULFILLING` — whose `deadline_at` now lies in the past is expired to `CLOSED_EXPIRED`; each such expiry appends a `REQUEST_CLOSED` audit entry — recorded with both its `actor_role` and `actor_user_id` set to the literal `system`, since the sweep has no acting operator — recomputes the owning controller's `open_request_count`, and bumps the request's `version`. Second, every processor notification still in `SENT` whose `ack_deadline_at` now lies in the past is marked `OVERDUE` as described in Section 3.6. Both sweeps are consequences of moving the clock and are not separately invokable.

Throughout the lifecycle, the append-only audit trail accumulates entries against the request, each stamped with the actor's `actor_role` and `actor_user_id`, an `event_type` drawn from `IDENTITY_VERIFIED`, `IDENTITY_REJECTED`, `DISCOVERY_RECORDED`, `EXEMPTION_DECIDED`, `FULFILLMENT_DISPATCHED`, `REQUEST_CLOSED`, and `DEADLINE_EXTENDED`, and a human-readable `detail`. This trail can be listed for a request and filtered by `event_type`.

### 3.9. Validation Ordering

When several checks apply to one operation, they are evaluated in a fixed priority order so that the failure reported is deterministic. Authentication comes first: a missing `X-User-ID` or `X-User-Role` yields `ERR_UNAUTHENTICATED`. Authorization is next: a role not permitted for the operation yields `ERR_UNAUTHORIZED`. Existence follows: any referenced resource that does not exist yields `ERR_NOT_FOUND`, checked left to right along the path. State validity is then checked: a target not in a valid state for the requested transition yields `ERR_INVALID_STATE`. Only after these structural checks do the domain rules apply — the deadline check (`ERR_DEADLINE_PASSED`), segregation of duties (`ERR_SEGREGATION_OF_DUTIES`), attempt exhaustion (`ERR_VERIFICATION_ATTEMPTS_EXHAUSTED`), the exemption-basis and legal-hold guards (`ERR_EXEMPTION_BASIS_UNSUPPORTED`, `ERR_LEGAL_HOLD_ACTIVE`), the undecided-exemption, unresolved-findings, no-findings, processor-suspended, notification-not-acknowledged, extension-limit, and fulfillment-incomplete guards — followed by the optimistic-concurrency check (`ERR_STALE_VERSION`) and finally body-integrity validation (`ERR_INVALID_REQUEST`).

## 4. Endpoint Definitions

Endpoints that create a brand-new resource return HTTP 201; all other successful operations, including state transitions and computed reads, return HTTP 200. Request bodies, response bodies, and side effects are not restated here — they are specified in the Section 3 narratives — so this table is a routing and authorization summary only.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/controllers` | Register a data controller (tenant) | `PrivacyOfficer` |
| GET | `/controllers/{id}` | Get a controller | `PrivacyOfficer`, `IntakeAgent` |
| POST | `/data-subjects` | Register a data subject under a controller | `IntakeAgent`, `PrivacyOfficer` |
| GET | `/data-subjects/{id}` | Get a data subject | `IntakeAgent`, `PrivacyOfficer` |
| GET | `/data-subjects` | List data subjects, optionally filtered by controller | `IntakeAgent`, `PrivacyOfficer` |
| POST | `/processors` | Register a processor (downstream vendor) | `PrivacyOfficer` |
| GET | `/processors/{id}` | Get a processor | `PrivacyOfficer`, `FulfillmentWorker` |
| GET | `/processors` | List processors, optionally filtered by controller | `PrivacyOfficer`, `FulfillmentWorker` |
| POST | `/processors/{id}/suspend` | Suspend a processor | `PrivacyOfficer` |
| POST | `/consent-records` | Record a consent grant for a subject and purpose | `IntakeAgent`, `PrivacyOfficer` |
| GET | `/consent-records/{id}` | Get a consent record | `IntakeAgent`, `PrivacyOfficer`, `DataSubjectAgent` |
| GET | `/consent-records` | List consent records, optionally filtered by subject | `IntakeAgent`, `PrivacyOfficer`, `DataSubjectAgent` |
| POST | `/consent-records/{id}/withdraw` | Subject withdraws a consent | `DataSubjectAgent`, `PrivacyOfficer` |
| POST | `/legal-holds` | Place a legal hold on a subject's data categories | `PrivacyOfficer` |
| GET | `/legal-holds/{id}` | Get a legal hold | `PrivacyOfficer` |
| GET | `/legal-holds` | List legal holds, optionally filtered by controller or subject | `PrivacyOfficer` |
| POST | `/legal-holds/{id}/lift` | Lift a legal hold | `PrivacyOfficer` |
| POST | `/dsar-requests` | Intake a new DSAR | `IntakeAgent`, `PrivacyOfficer` |
| GET | `/dsar-requests/{id}` | Get a DSAR (includes computed deadline and progress fields) | `IntakeAgent`, `PrivacyOfficer`, `FulfillmentWorker` |
| GET | `/dsar-requests` | List DSARs, optionally filtered by controller, subject, or status | `IntakeAgent`, `PrivacyOfficer`, `FulfillmentWorker` |
| GET | `/dsar-requests/{id}/risk` | Computed read: erasure exposure risk score for a deletion request | `PrivacyOfficer` |
| POST | `/dsar-requests/{id}/verify-identity` | Verify subject identity | `IntakeAgent` |
| POST | `/dsar-requests/{id}/reject-identity` | Reject identity evidence | `IntakeAgent` |
| POST | `/dsar-requests/{id}/resubmit-identity` | Resubmit identity evidence | `IntakeAgent` |
| POST | `/dsar-requests/{id}/complete-discovery` | Close discovery | `PrivacyOfficer` |
| POST | `/dsar-requests/{id}/extend-deadline` | Grant the single permitted deadline extension | `PrivacyOfficer` |
| POST | `/dsar-requests/{id}/dispatch-fulfillment` | Fan out fulfillment items (OCC-guarded) | `PrivacyOfficer` |
| POST | `/dsar-requests/{id}/close` | Close the request (fulfilled or rejected) | `PrivacyOfficer` |
| POST | `/dsar-requests/{id}/findings` | Record a cross-system discovery finding | `PrivacyOfficer`, `IntakeAgent` |
| GET | `/dsar-requests/{id}/findings` | List a request's discovery findings | `PrivacyOfficer`, `IntakeAgent`, `FulfillmentWorker` |
| GET | `/findings/{id}` | Get a single discovery finding | `PrivacyOfficer`, `IntakeAgent`, `FulfillmentWorker` |
| GET | `/findings` | List discovery findings, filtered by processor or request | `PrivacyOfficer`, `IntakeAgent`, `FulfillmentWorker` |
| POST | `/findings/{id}/confirm` | Confirm a discovery finding | `PrivacyOfficer` |
| POST | `/findings/{id}/dismiss` | Dismiss a discovery finding | `PrivacyOfficer` |
| POST | `/dsar-requests/{id}/exemptions` | Assert an exemption against a request | `PrivacyOfficer` |
| GET | `/dsar-requests/{id}/exemptions` | List a request's exemption claims | `PrivacyOfficer` |
| GET | `/exemptions/{id}` | Get a single exemption claim | `PrivacyOfficer` |
| POST | `/exemptions/{id}/decide` | Uphold or overrule an exemption | `PrivacyOfficer` |
| GET | `/dsar-requests/{id}/fulfillment-items` | List a request's fulfillment items | `PrivacyOfficer`, `FulfillmentWorker` |
| GET | `/fulfillment-items/{id}` | Get a single fulfillment item | `PrivacyOfficer`, `FulfillmentWorker` |
| GET | `/fulfillment-items` | List fulfillment items, filtered by finding, processor, or request | `PrivacyOfficer`, `FulfillmentWorker` |
| POST | `/fulfillment-items/{id}/dispatch` | Dispatch an item to its processor (OCC-guarded) | `FulfillmentWorker` |
| POST | `/fulfillment-items/{id}/complete` | Mark an item complete after processor acknowledgement | `FulfillmentWorker` |
| POST | `/fulfillment-items/{id}/unblock` | Return a blocked item to the queue after a hold is lifted | `PrivacyOfficer` |
| GET | `/fulfillment-items/{id}/notifications` | List notifications for an item | `PrivacyOfficer`, `FulfillmentWorker`, `ProcessorAgent` |
| GET | `/processor-notifications/{id}` | Get a single processor notification | `PrivacyOfficer`, `FulfillmentWorker`, `ProcessorAgent` |
| GET | `/processor-notifications` | List processor notifications, filtered by processor | `PrivacyOfficer`, `FulfillmentWorker`, `ProcessorAgent` |
| POST | `/processor-notifications/{id}/acknowledge` | Acknowledge a notification | `ProcessorAgent` |
| GET | `/dsar-requests/{id}/audit-events` | List a request's audit events | `PrivacyOfficer`, `IntakeAgent` |
| POST | `/_clock/set_current_utc` | Set the server's notion of now; triggers expiry and overdue sweeps | `PrivacyOfficer` |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| --- | --- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_DEADLINE_PASSED` | 409 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_VERIFICATION_ATTEMPTS_EXHAUSTED` | 409 |
| `ERR_EXEMPTION_BASIS_UNSUPPORTED` | 409 |
| `ERR_LEGAL_HOLD_ACTIVE` | 409 |
| `ERR_UNDECIDED_EXEMPTION` | 409 |
| `ERR_UNRESOLVED_FINDINGS` | 409 |
| `ERR_NO_FINDINGS` | 409 |
| `ERR_PROCESSOR_SUSPENDED` | 409 |
| `ERR_NOTIFICATION_NOT_ACKED` | 409 |
| `ERR_EXTENSION_LIMIT_REACHED` | 409 |
| `ERR_FULFILLMENT_INCOMPLETE` | 409 |
| `ERR_STALE_VERSION` | 412 |
