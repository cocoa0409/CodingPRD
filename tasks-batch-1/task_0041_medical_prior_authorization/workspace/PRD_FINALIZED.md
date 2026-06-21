# Medical Prior Authorization API — Product Requirements Document

## 1. Introduction

Prior authorization is the gatekeeping process by which a health plan decides, before care is rendered, whether it will cover a requested medical service or drug. This API models that workflow end-to-end. A requesting provider assembles a pre-approval request, attaches the clinical evidence that justifies medical necessity, and submits it to the patient's insurance payer. A clinical reviewer on the payer's side then renders a decision — approving, partially approving, denying, or pending the request for more information — and may convene a Peer-to-Peer discussion with the requesting provider before deciding. Urgent cases travel an expedited track with tighter turnaround clocks.

When a request is denied, the provider is not without recourse: a three-tier appeal process allows escalation from internal reconsideration, to an internal medical director, and finally to a binding external Independent Review Organization. Authorizations that are granted do not last forever; they expire, and when they do the provider may resubmit a fresh request that supersedes the lapsed one. The system is built around a controllable logical clock so that service-level-agreement deadlines, appeal windows, and expiration can be exercised deterministically. Throughout, the design emphasizes immediate consistency: every approval, overturn, and expiration that touches a member's standing is reflected at once across the affected records.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and cross-cutting principles that govern every endpoint.

### 2.1. User and Role-Based Access Control

Every request to a protected endpoint must carry two HTTP headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, declaring the capacity in which that principal acts. When either header is missing or malformed on a protected endpoint, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). When the headers are well-formed but the declared role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN` (HTTP 403). Authentication is evaluated before authorization.

The system recognizes four roles, spelled exactly: `Anonymous`, `Provider`, `Payer`, and `ExternalReviewer`. The four registration endpoints — creating a provider, creating a payer, creating a member, and creating a reviewer — form the unauthenticated registration surface and do not require the headers; every other endpoint does.

The `X-User-ID` header is interpreted differently per role:

- When `X-User-Role` is `Provider`, `X-User-ID` is the `id` of the acting `Provider`; ownership checks on any resource that references a `Provider` compare the resource's `provider_id` to `X-User-ID`. A provider may submit only its own requests and may file or withdraw appeals only on requests it owns.
- When `X-User-Role` is `Payer`, `X-User-ID` is the `id` of the acting `Payer`; ownership checks on any resource that references a `Payer` compare the resource's `payer_id` to `X-User-ID`. A payer may act only on requests whose `payer_id` equals its own `id`.
- When `X-User-Role` is `Anonymous`, `X-User-ID` is an opaque identifier not tied to any persisted entity; the registration surface neither records nor compares it to any entity's `id`.
- When `X-User-Role` is `ExternalReviewer`, `X-User-ID` is an opaque operator identifier representing the Independent Review Organization; it is not tied to any persisted entity and the server does not compare it to any entity's `id`.

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

List endpoints accept two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0, with a minimum of 0. A `limit` or `offset` outside these bounds is rejected with `ERR_PAGINATION_INVALID` (HTTP 400).

Unless otherwise specified, all list endpoints return resources sorted by their `created_at` timestamp in ascending order. List responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. The Logical Clock and Time-Driven Behavior

The server keeps a single logical UTC clock that governs every time-stamped field and every deadline comparison. A test-driving capability pins this clock to a supplied instant, provided as the `to_iso8601` field; this is available to the `Provider`, `Payer`, and `ExternalReviewer` roles. Pinning the clock does not itself trigger any automatic expiry sweep — an approved authorization is moved to its expired state only by an explicit expire capability described in §3, never as a side effect of setting the clock.

All timestamp fields — including `submitted_at`, `review_started_at`, `sla_due_at`, `authorization_expires_at`, `filed_at`, `appeal_deadline_at`, `slot_start`, and `slot_end` — are ISO 8601 UTC values resolved to the second. The deadline comparisons described in §3 read the current value of this clock.

### 2.5. Common Resource Properties and Versioning

Most resources carry a standard set of system-managed fields. The `id` is a server-minted UUID with no type prefix. The `created_at` field is an ISO 8601 UTC timestamp with three fractional digits, fixed at creation. The `updated_at` field is an ISO 8601 UTC timestamp refreshed on every mutation. The `version` field is an integer that begins at its initial value and increments by one on every mutation of the resource.

This full set — `id`, `created_at`, `updated_at`, and `version` — applies to `Provider`, `Payer`, `Member`, `AuthorizationRequest`, `ReviewDecision`, `PeerToPeerSession`, `Reviewer`, and `Appeal`. The one exception is `ClinicalEvidence`, which is immutable after upload: an evidence record carries only `id` and `created_at`, and has neither `updated_at` nor `version`.

### 2.6. Hierarchical Consistency and Cascading Effects

Several operations mutate more than one resource. Whenever a single operation changes a secondary resource, that change is applied immediately and the secondary resource's own `updated_at` is refreshed and its `version` incremented. The two principal cascades are the member-counter cascade — where approving, overturning, or expiring an authorization adjusts the referenced member's running count of active authorizations — and the SLA-clock cascade — where completing a Peer-to-Peer session credits paused time back onto its linked request and recomputes that request's review deadline. Each is specified in full in §3 near the workflow that triggers it. The guiding rule is that no derived counter, deadline, or status is left stale after the operation that affects it returns.

### 2.7. Nested Resource Retrieval and Reference Validation

Resources reference one another by foreign-key fields carried in the request body rather than by nested URL paths. On every request, the system validates references left-to-right: any identifier appearing in the URL path is checked before any foreign key in the body, and the first reference that does not resolve to an existing row causes the request to be rejected with `ERR_NOT_FOUND` (HTTP 404). This ordering ensures a missing path target is reported before any body-level reference is examined.

List endpoints expose foreign-key filters so that children can be reached from their parents: members and reviewers may be filtered by `payer_id`; clinical evidence by `request_id`; review decisions by `request_id` and `reviewer_id`; peer-to-peer sessions by `request_id` and `reviewer_id`; appeals by `request_id`; and authorization requests by `member_id`, `provider_id`, `payer_id`, `status`, and the self-referential `supersedes_request_id`.

### 2.8. Cost Precision and Rounding

All monetary amounts are integer counts of cents, so two implied decimal places of currency precision are preserved exactly. Wherever the coinsurance computation multiplies a cent amount by the member's cost-share fraction, the product is rounded half up to the nearest whole cent. Crucially, this rounding is applied per line item before any summation — never sum-then-round. The procedure component and each individual evidence line are each rounded to a whole cent first, and only the already-rounded whole-cent results are added together.

### 2.9. Service-Level-Agreement and Appeal-Window Timekeeping

Two distinct clocks bound the workflow. The review SLA clock measures how long the payer has to render a decision and is captured in `sla_due_at`; it can be paused while a request awaits more information or while a Peer-to-Peer discussion is pending. Separately, each appeal tier carries its own decision window captured in `appeal_deadline_at`. Both clocks are enforced as hard deadlines: a review or appeal decision rendered after its respective deadline is rejected. The exact formulas — including the accumulation of paused hours in `clock_paused_hours` and the per-tier appeal windows — appear in §3 alongside the workflows they govern.

### 2.10. Optimistic Concurrency on Resubmission

Resubmitting a request that supersedes an expired one is the single optimistic-concurrency-controlled write in the system. The create-request endpoint, when it carries a `supersedes_request_id`, must also carry `expected_authorizationrequest_version` holding the client's last observed `version` of the targeted expired request. If that expired request's current `version` no longer matches — for instance because another resubmission has already superseded it, legitimately advancing its `version` and flipping it to its superseded state — the client's view is stale and the create is rejected with `ERR_STALE_VERSION` (HTTP 412). This prevents a client from superseding a request whose state it has not actually observed. Endpoints other than the resubmitting create do not take a version field.

## 3. Business Logic & Workflows

### 3.1. Registering the Participants

Four kinds of actor are registered through the open registration surface. A `Provider` is created with its `npi` — the National Provider Identifier, which must be exactly 10 numeric characters, is required, and must be unique across providers — together with a `name` (required, non-empty) and a `specialty` drawn from `CARDIOLOGY`, `ONCOLOGY`, `ORTHOPEDICS`, `NEUROLOGY`, `PRIMARY_CARE`, or `RADIOLOGY`.

A `Payer` is created with a `name` (required, non-empty) and two turnaround settings. The `standard_sla_hours` field is the number of hours allowed for an ordinary, non-expedited review; it must be at least 1 and defaults to 168. The `expedited_sla_hours` field is the number of hours allowed for an urgent review; it must be at least 1, must be strictly less than `standard_sla_hours`, and defaults to 72.

A `Member` is registered under a payer by supplying a `payer_id` that must reference an existing `Payer`, a `member_number` that is required and unique within that payer, and an optional `coinsurance_rate` — the fraction of approved cost the member bears out of pocket — which must be at least 0.0 and at most 1.0 and defaults to 0.2. Each member also exposes a computed `active_authorization_count`, described in §3.5.

A `Reviewer` is a clinical reviewer employed by a payer, registered with a `payer_id` referencing an existing `Payer`, a `name` (required, non-empty), a `specialty` from the same six-value set as providers, and an optional `p2p_buffer_minutes` — the minimum gap this reviewer requires between two of their discussion slots — which must be at least 0 and defaults to 0.

### 3.2. Building and Submitting an Authorization Request

A `Provider` opens a prior-authorization request, which is always created in the `DRAFT` state regardless of any `status` or other system-managed field supplied in the payload; such non-input fields are ignored rather than rejected, and they do not trigger `ERR_VALIDATION`. The creation payload carries the `member_id` (must reference an existing `Member`), the `provider_id` (must reference an existing `Provider`), a `request_type` of either `SERVICE` or `DRUG`, a `procedure_code` (the CPT/HCPCS code for a service or the NDC code for a drug; required, non-empty), the `requested_units` (the number of units, sessions, or days, which must be at least 1), and the `unit_cost_cents` (the payer's allowed cost per unit in cents, which must be at least 0). The requester may set `is_expedited` to flag the case as urgent; it defaults to false. At creation the system copies the member's payer onto the request's `payer_id` field, so the request inherits the member's insurer automatically. A request may also carry a `supersedes_request_id` and an `expected_authorizationrequest_version` — these drive resubmission and are covered in §3.7.

Clinical evidence is uploaded separately. A `Provider` uploads a `ClinicalEvidence` document by supplying the `request_id` it supports (must reference an existing `AuthorizationRequest`), a `document_type` from `CHART_NOTE`, `LAB_RESULT`, `IMAGING`, `MEDICATION_HISTORY`, or `LETTER_OF_MEDICAL_NECESSITY`, a `line_item_cost_cents` (the documented cost attributable to this evidence line, in cents, at least 0), and a `uri` pointing at the stored document (required, non-empty).

Submitting moves the request from `DRAFT` to `SUBMITTED`. The acting provider must own the request — its `provider_id` must equal `X-User-ID` — and at least one `ClinicalEvidence` row must already exist for the request; an attempt to submit a request with zero evidence rows is rejected with `ERR_NO_EVIDENCE` (HTTP 422). On a successful submit the system sets `submitted_at` to the current clock, sets `review_started_at` to the current clock, computes `sla_due_at` from those values with `clock_paused_hours` starting at 0, computes the member's `member_cost_share_cents`, and increments the request's `version` by one. The `submitted_at` field is null while the request is still `DRAFT`.

### 3.3. Payer Review and the Four Decision Outcomes

The payer that owns a `SUBMITTED` request begins examining it, transitioning it from `SUBMITTED` to `UNDER_REVIEW`. The acting payer's `id` must equal the request's `payer_id`. Starting review resets `review_started_at` to the current clock, recomputes `sla_due_at`, and increments the request's `version` by one.

A clinical reviewer then renders a `ReviewDecision` against a request that is `UNDER_REVIEW`. The decision payload carries the `request_id` (must reference a request currently `UNDER_REVIEW`), the `reviewer_id` (must reference a `Reviewer` whose `payer_id` equals the request's `payer_id`), an `outcome` of `APPROVE`, `PARTIAL`, `DENY`, or `PEND`, and depending on the outcome an `approved_units`, a `rationale`, and a `pend_reason`. A reviewer whose `payer_id` does not match the request's `payer_id` is rejected with `ERR_REVIEWER_PAYER_MISMATCH` (HTTP 422) — a reviewer may act only on its own payer's requests.

The four outcomes drive four different transitions out of `UNDER_REVIEW`, and they must be specified with equal care:

- An `APPROVE` outcome moves the request to `APPROVED`. The `approved_units` is forced to equal the request's `requested_units` (any supplied value is ignored for full approval). The decision creates the `ReviewDecision` row, sets the request's `approved_units` accordingly, recomputes `member_cost_share_cents` using the approved units, sets `authorization_expires_at` to the current clock plus 365 days, increments the referenced member's `active_authorization_count` by one as a cross-aggregate cascade, and increments the request's `version` by one.
- A `PARTIAL` outcome also moves the request to `APPROVED`, but the reviewer's supplied `approved_units` is honored. For a partial approval `approved_units` is required, must be at least 1, and must be strictly less than the request's `requested_units`; a `rationale` is required. The same approval cascade applies: the request's `approved_units` is set to the reduced count, `member_cost_share_cents` is recomputed from that smaller count (yielding a smaller cost share than a full approval of the same request), `authorization_expires_at` is set to the current clock plus 365 days, the member's `active_authorization_count` is incremented by one, and the request's `version` is incremented by one.
- A `DENY` outcome moves the request to `DENIED`. A `rationale` is required. The decision creates the `ReviewDecision` row, sets the request's `approved_units` to 0, and increments the request's `version` by one. A denial opens the appeal pathway described in §3.6.
- A `PEND` outcome moves the request to `PENDED`. A `pend_reason` of `INSUFFICIENT_EVIDENCE`, `MISSING_LMN`, or `PEER_TO_PEER_REQUIRED` is required. The decision creates the `ReviewDecision` row, records the instant pending began so that paused time can later be measured, and increments the request's `version` by one. While the request sits in `PENDED` its SLA clock is paused, as detailed in §3.4.

If the decision-field combination is invalid — a `PARTIAL` whose units fall outside the range from 1 up to but not including `requested_units`, an `APPROVE` on a request that is already terminal, a missing `rationale` on a `DENY` or `PARTIAL`, or a missing `pend_reason` on a `PEND` — the request is rejected with `ERR_INVALID_DECISION_FIELDS` (HTTP 422).

A pended request returns to review when the provider supplies more information. Resuming moves the request from `PENDED` back to `UNDER_REVIEW`; the acting payer's `id` must equal the request's `payer_id`, and at least one new `ClinicalEvidence` row must have been added for the request after the pend decision was recorded; "after" is determined by creation order rather than by timestamp comparison, so evidence created later in the sequence of operations counts as new even when the logical clock is pinned and its `created_at` equals the instant the pend was recorded. When no such new evidence exists, the resume is rejected with `ERR_NO_EVIDENCE` (HTTP 422). Resuming adds the hours elapsed since pending began to `clock_paused_hours`, resets `review_started_at` to the current clock, recomputes `sla_due_at` so it now reflects the larger `clock_paused_hours`, and increments the request's `version` by one.

### 3.4. Peer-to-Peer Discussions and the SLA Clock

Before deciding, a payer may schedule a Peer-to-Peer discussion. A `PeerToPeerSession` is created with the `request_id` (must reference a request currently `UNDER_REVIEW` or `PENDED`), the `reviewer_id` (must reference a `Reviewer` whose `payer_id` equals the request's `payer_id`, again guarded by `ERR_REVIEWER_PAYER_MISMATCH`), an inclusive `slot_start`, and an exclusive `slot_end` that must be strictly after `slot_start`. A session is created in the `SCHEDULED` state.

Slots for the same reviewer may not collide. A proposed slot, treated as the half-open interval from `slot_start` up to but not including `slot_end`, conflicts with any other non-`CANCELLED` slot of the same reviewer when the two intervals overlap, or when the gap between them is less than that reviewer's `p2p_buffer_minutes`. A conflicting slot is rejected with `ERR_P2P_SLOT_CONFLICT` (HTTP 409).

An open Peer-to-Peer session blocks decision-making: no `ReviewDecision` may be rendered for a request while any of that request's sessions is still `SCHEDULED`. The session must first be completed or cancelled. An attempt to decide over a still-`SCHEDULED` session is rejected with `ERR_OPEN_P2P_BLOCKS_DECISION` (HTTP 409); this applies specifically to rendering a review decision.

Completing a session moves it from `SCHEDULED` to `COMPLETED`. The acting payer's `id` must equal the linked request's `payer_id`. Completion adds the slot's duration — the hours from `slot_start` to `slot_end` — to the linked request's `clock_paused_hours`, recomputes that request's `sla_due_at`, and increments the session's `version` by one. Cancelling instead moves the session from `SCHEDULED` to `CANCELLED`, again requiring the acting payer to own the linked request; cancellation frees the reviewer's slot, credits no paused time, and increments the session's `version` by one.

The review deadline itself is computed as follows. The base allowance is the payer's `expedited_sla_hours` when the request's `is_expedited` flag is true, and the payer's `standard_sla_hours` when it is false; the expedited default is 72 hours and the standard default is 168 hours. The deadline `sla_due_at` is then `review_started_at` advanced by the sum of that base allowance and the accumulated `clock_paused_hours`, where `clock_paused_hours` is the running total of time spent pended plus the duration of every `COMPLETED` Peer-to-Peer session linked to this request. Because an expedited request uses the smaller base, it yields an earlier deadline than a standard request that started review at the same instant. The arithmetic is performed in whole hours and the resulting datetime is resolved to the second.

### 3.5. Cost Sharing and the Member's Active-Authorization Counter

The member's estimated out-of-pocket amount, `member_cost_share_cents`, is the sum of two separately rounded components. The first is the procedure cost share: the system multiplies the request's `unit_cost_cents` by the member's `coinsurance_rate`, rounds that single-unit product half up to a whole cent, and then multiplies the rounded per-unit share by the effective number of units. The effective units are the request's `requested_units` while the request has not yet been approved, and the request's `approved_units` once it has been approved. The second component is the evidence cost share: for each `ClinicalEvidence` row attached to the request — all of them, with no status filter, because evidence has no lifecycle — the system multiplies that line's `line_item_cost_cents` by the member's `coinsurance_rate`, rounds each line half up to a whole cent, and sums those rounded line amounts. The member's total cost share is the rounded procedure share plus the summed rounded evidence shares; rounding is always per line item before summing.

This figure is computed when the request is first submitted (using `requested_units`), recomputed when the request is approved (using `approved_units`), and recomputed again when a denial is later overturned on appeal.

Each `Member` carries a computed `active_authorization_count`: the number of that member's authorization requests in the `APPROVED` state whose `authorization_expires_at` is still in the future relative to the current clock. It is recomputed as a side effect of every approval, expiration, and supersede event. Concretely, the counter is incremented by one whenever one of the member's requests enters `APPROVED` (whether by a direct review decision or by an appeal overturn), and decremented by one — floored at zero — whenever an `APPROVED` request expires.

### 3.6. The Three-Tier Appeal Process

A denial is appealable. A `Provider` files an `Appeal` by supplying the `request_id` of a request currently in `DENIED` status. A first appeal is created at `tier` 1, in the `OPEN` state, with `filed_at` set to the current clock; the system also computes the appeal's `appeal_deadline_at`. Filing an appeal on a request that is not `DENIED`, or filing when the eligibility conditions for escalation are not met, is rejected with `ERR_APPEAL_NOT_ELIGIBLE` (HTTP 422). The three tiers represent internal reconsideration at `tier` 1, internal medical-director review at `tier` 2, and external Independent Review Organization review at `tier` 3.

Tier-1 and tier-2 appeals are decided by the payer. Deciding an `OPEN` appeal requires the acting payer's `id` to equal the payer of the appeal's underlying request, the appeal's `tier` to be 1 or 2, a `decision_rationale` to be present, and the current clock to be at or before `appeal_deadline_at`. The supplied `decision` is either `UPHELD` or `OVERTURNED`:

- An `UPHELD` decision sets the appeal's `status` to `UPHELD` and leaves the underlying request in `DENIED`; the member may then escalate to the next tier. The appeal's `version` increments by one.
- An `OVERTURNED` decision sets the appeal's `status` to `OVERTURNED` and cascades back to the underlying request: the request transitions from `DENIED` to `APPROVED`, its `approved_units` is set to `requested_units`, its `authorization_expires_at` is set to the current clock plus 365 days, its `member_cost_share_cents` is recomputed, and the referenced member's `active_authorization_count` is incremented by one. The appeal's `version` increments by one. This is a three-hop cascade: appeal to request to member counter.

Tier-3 appeals are decided only by the `ExternalReviewer`, who renders a binding decision. The external decision requires the appeal's `tier` to be 3, a `decision_rationale` to be present, and the current clock to be at or before `appeal_deadline_at`. Its two branches mirror the payer's with equal effect:

- An `OVERTURNED` external decision sets the appeal's `status` to `OVERTURNED` and applies the identical cascade — the underlying request moves from `DENIED` to `APPROVED`, `approved_units` is set to `requested_units`, `authorization_expires_at` is set to the current clock plus 365 days, `member_cost_share_cents` is recomputed, and the member's `active_authorization_count` is incremented by one — and increments the appeal's `version` by one.
- An `UPHELD` external decision sets the appeal's `status` to `UPHELD` and leaves the underlying request in `DENIED`; this is final, with no further escalation. The appeal's `version` increments by one.

Escalation chains the tiers together. When a prior appeal for a request is `UPHELD` and its `tier` is less than 3, and no other `OPEN` appeal exists for that request, the provider may escalate by filing again on the same request. Escalation sets the prior appeal's `status` to `ESCALATED`, increments the prior appeal's `version` by one, and creates a new `Appeal` whose `tier` is the prior tier plus one, in the `OPEN` state, with `filed_at` at the current clock and a freshly computed `appeal_deadline_at`. The eligibility guard — prior appeal `UPHELD` with `tier` below 3 and no `OPEN` appeal outstanding — is enforced with `ERR_APPEAL_NOT_ELIGIBLE`.

A provider may also withdraw an `OPEN` appeal, moving it to `WITHDRAWN`, provided the appeal belongs to the request's owning provider — the request's `provider_id` must equal `X-User-ID`. Withdrawal increments the appeal's `version` by one.

The appeal-decision window is computed per tier. Each tier has a base window in days — 30 days for tier 1, 30 days for tier 2, and 45 days for tier 3. Expedited requests compress this window: when the underlying request's `is_expedited` flag is true the window is multiplied by 0.25, and when it is false the full tier window applies. The `appeal_deadline_at` is the appeal's `filed_at` advanced by the resulting number of days; the window may be fractional, and the deadline datetime is resolved to the second. A review or appeal decision rendered after its deadline — past `sla_due_at` for a review decision, or past `appeal_deadline_at` for an appeal decision — is rejected with `ERR_PAST_DEADLINE` (HTTP 409).

### 3.7. Expiration, Resubmission, and Supersession

An `APPROVED` authorization carries an `authorization_expires_at`. Once the current clock reaches or passes that instant, the payer may force the request to `EXPIRED` through an explicit expire capability; the precondition is that the current clock is at or after `authorization_expires_at`. Expiring sets the request's `status` to `EXPIRED`, decrements the referenced member's `active_authorization_count` by one (floored at zero) as a cross-aggregate cascade, and increments the request's `version` by one. Expiry is never triggered merely by advancing the clock; it requires this explicit action.

A provider may resubmit against an expired request. A resubmission is a new authorization-request create that carries a `supersedes_request_id` pointing at the `EXPIRED` request it replaces; an original request leaves this field null. The supersede target must reference an `EXPIRED` request owned by the same `member_id` and `provider_id` as the new request and not already superseded by another request; a target that is not `EXPIRED`, belongs to a different member or provider, or has already been superseded is rejected with `ERR_INVALID_SUPERSEDE_TARGET` (HTTP 422) — except for the §2.10 carve-out, where a target that has already been superseded *and* whose current `version` no longer matches the supplied `expected_authorizationrequest_version` is reported as `ERR_STALE_VERSION` instead (see §2.10 and §3.9). The resubmission must also carry `expected_authorizationrequest_version` equal to the target request's current `version`; if it does not match, the create is rejected with `ERR_STALE_VERSION` (HTTP 412), as described in §2.10.

When a valid resubmission is accepted, the targeted `EXPIRED` request transitions to `SUPERSEDED` and its `version` is incremented by one, while the new resubmission request is created in `DRAFT`, copying the `request_type`, `procedure_code`, `requested_units`, and `unit_cost_cents` from the superseded request. The targeted request must have no other request already referencing it via `supersedes_request_id`. The `SUPERSEDED` state is terminal for the original request.

### 3.8. Guarding Against Duplicate Active Coverage

The system permits exactly one concurrent active authorization per member and procedure code. Approving a request — whether through a review decision, a tier-1/2 appeal decision, or a tier-3 external decision — is blocked when it would create a duplicate active authorization. The coverage interval of a request is the closed interval running from its `submitted_at` to its `authorization_expires_at`. An approval is rejected with `ERR_DUPLICATE_ACTIVE_AUTH` (HTTP 409) when this interval would overlap the coverage interval of any existing `APPROVED` request — one that is neither `EXPIRED` nor `SUPERSEDED` — for the same member and the same `procedure_code`. Because the interval is closed, two intervals that merely touch at an endpoint count as overlapping.

### 3.9. Validation Ordering

When several checks apply to one operation, they are evaluated in a fixed priority order so that the earliest applicable failure is the one reported. Authentication of the headers comes first (`ERR_UNAUTHENTICATED`), then role authorization (`ERR_FORBIDDEN`), then existence of every referenced row validated left-to-right with path identifiers before body foreign keys (`ERR_NOT_FOUND`), then whether the target resource is in a state from which the requested transition is defined (`ERR_INVALID_STATE`, HTTP 409). After those structural checks come the business rules in order: the reviewer-payer match (`ERR_REVIEWER_PAYER_MISMATCH`), the open-Peer-to-Peer block on decisions (`ERR_OPEN_P2P_BLOCKS_DECISION`), the evidence requirement on submit (`ERR_NO_EVIDENCE`), the Peer-to-Peer slot-conflict check (`ERR_P2P_SLOT_CONFLICT`), the duplicate-active-authorization check (`ERR_DUPLICATE_ACTIVE_AUTH`), the deadline check (`ERR_PAST_DEADLINE`), the decision-field validity check (`ERR_INVALID_DECISION_FIELDS`), the appeal-eligibility check (`ERR_APPEAL_NOT_ELIGIBLE`), the supersede-target check (`ERR_INVALID_SUPERSEDE_TARGET`), and finally the stale-version check (`ERR_STALE_VERSION`). This supersede-target-before-stale-version ordering has one carve-out, governed by the more specific rule in §2.10: when the targeted request has already been superseded by another resubmission *and* the supplied `expected_authorizationrequest_version` no longer matches the target's current `version`, that combined condition is reported as `ERR_STALE_VERSION` rather than `ERR_INVALID_SUPERSEDE_TARGET`. All other invalid-target conditions — a target that is not `EXPIRED`, or that belongs to a different `member_id` or `provider_id`, or that has already been superseded while the supplied version still matches — are still reported as `ERR_INVALID_SUPERSEDE_TARGET` ahead of the stale-version check. A request missing a required input field or carrying a value of the wrong type, enum, or range is rejected with `ERR_VALIDATION` (HTTP 422).

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource return a `201 Created` status code; operations that modify an existing resource, including state-transition actions, return a `200 OK` status code. All endpoints emit the standard envelope of §2.2.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/providers` | Register a provider | Anonymous |
| GET | `/providers/{id}` | Fetch a provider | Provider, Payer, ExternalReviewer |
| POST | `/payers` | Register a payer | Anonymous |
| GET | `/payers/{id}` | Fetch a payer | Provider, Payer, ExternalReviewer |
| POST | `/members` | Register a member under a payer | Anonymous |
| GET | `/members/{id}` | Fetch a member, including computed active authorization count | Provider, Payer |
| GET | `/members` | List members, optionally filtered by payer | Provider, Payer |
| POST | `/reviewers` | Register a payer clinical reviewer | Anonymous |
| GET | `/reviewers/{id}` | Fetch a reviewer | Provider, Payer |
| GET | `/reviewers` | List reviewers, optionally filtered by payer | Provider, Payer |
| POST | `/authorization-requests` | Create a prior-authorization request in DRAFT, or a resubmission superseding an EXPIRED request | Provider |
| GET | `/authorization-requests/{id}` | Fetch a request with all computed fields | Provider, Payer, ExternalReviewer |
| GET | `/authorization-requests` | List requests, filterable by member, provider, payer, status, supersedes target | Provider, Payer, ExternalReviewer |
| POST | `/authorization-requests/{id}/submit` | Submit a DRAFT request for review | Provider |
| POST | `/authorization-requests/{id}/start-review` | Move a SUBMITTED request to UNDER_REVIEW | Payer |
| POST | `/authorization-requests/{id}/resume-review` | Resume a PENDED request to UNDER_REVIEW once new evidence is supplied | Payer |
| POST | `/authorization-requests/{id}/expire` | Force an APPROVED request to EXPIRED at/after its expiry instant | Payer |
| POST | `/clinical-evidence` | Upload a clinical evidence document for a request | Provider |
| GET | `/clinical-evidence/{id}` | Fetch one evidence document | Provider, Payer, ExternalReviewer |
| GET | `/clinical-evidence` | List evidence, filterable by request | Provider, Payer, ExternalReviewer |
| POST | `/review-decisions` | Render a decision on an UNDER_REVIEW request | Payer |
| GET | `/review-decisions/{id}` | Fetch a review decision | Provider, Payer, ExternalReviewer |
| GET | `/review-decisions` | List decisions, filterable by request and reviewer | Provider, Payer, ExternalReviewer |
| POST | `/peer-to-peer-sessions` | Schedule a Peer-to-Peer discussion slot | Payer |
| GET | `/peer-to-peer-sessions/{id}` | Fetch a P2P session | Provider, Payer |
| GET | `/peer-to-peer-sessions` | List P2P sessions, filterable by request and reviewer | Provider, Payer |
| POST | `/peer-to-peer-sessions/{id}/complete` | Mark a P2P slot COMPLETED and credit its duration to SLA pause | Payer |
| POST | `/peer-to-peer-sessions/{id}/cancel` | Cancel a SCHEDULED P2P slot | Payer |
| POST | `/appeals` | File a tier-1 appeal on a DENIED request, or escalate after an UPHELD appeal | Provider |
| GET | `/appeals/{id}` | Fetch an appeal | Provider, Payer, ExternalReviewer |
| GET | `/appeals` | List appeals, filterable by request | Provider, Payer, ExternalReviewer |
| POST | `/appeals/{id}/decide` | Render a tier-1 or tier-2 appeal decision | Payer |
| POST | `/appeals/{id}/external-decide` | Render a binding tier-3 appeal decision | ExternalReviewer |
| POST | `/appeals/{id}/withdraw` | Withdraw an OPEN appeal | Provider |
| POST | `/_clock/set_current_utc` | Test-driving: pin the server's current UTC clock | Provider, Payer, ExternalReviewer |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_REVIEWER_PAYER_MISMATCH` | 422 |
| `ERR_OPEN_P2P_BLOCKS_DECISION` | 409 |
| `ERR_NO_EVIDENCE` | 422 |
| `ERR_P2P_SLOT_CONFLICT` | 409 |
| `ERR_PAST_DEADLINE` | 409 |
| `ERR_DUPLICATE_ACTIVE_AUTH` | 409 |
| `ERR_INVALID_DECISION_FIELDS` | 422 |
| `ERR_APPEAL_NOT_ELIGIBLE` | 422 |
| `ERR_INVALID_SUPERSEDE_TARGET` | 422 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_VALIDATION` | 422 |
| `ERR_PAGINATION_INVALID` | 400 |
