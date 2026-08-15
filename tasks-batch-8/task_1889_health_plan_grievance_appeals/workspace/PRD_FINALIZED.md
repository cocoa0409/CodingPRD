# Health Plan Grievance Appeals API — Product Requirements Document

## 1. Introduction

Health plans administering Medicare and Medi-Cal (Medicaid) lines of business operate under some of the most unforgiving regulatory clocks in American healthcare. Every member complaint — whether a quality-of-care grievance, a dispute over an organization determination, or a formal appeal of an adverse decision — arrives with a federally prescribed resolution timeframe, prescribed notification content, prescribed escalation paths to an Independent Review Entity (IRE), and an audit trail that regulators sample without warning. Missing a 24-hour acknowledgement, mailing an incomplete decision letter, or sitting on an effectuation past its window is not a customer-service blemish; it is a compliance finding with monetary and star-rating consequences.

This document specifies the Health Plan Grievance Appeals API, mounted under `/appeals`, which operationalizes that entire regulatory surface as a deterministic workflow engine. The system governs case intake and classification across the three case kinds (grievance, organization determination, appeal), standard versus expedited timeframe tracks, physician-led clinical review culminating in a medical director determination, member and provider notification with enforced content completeness, IRE forwarding and effectuation of overturned decisions, reopening of closed cases, linkage into the Complaint Tracking Module (CTM), and the periodic audit-universe snapshot that compliance teams hand to auditors. A logical server clock drives every deadline computation so that timeliness is reproducible and testable rather than hostage to wall-clock time.

The intended operators are plan staff working under strict segregation of duties: intake specialists, utilization-management analysts, medical directors, member services representatives, compliance officers, claims processors, and platform administrators. No single operator may shepherd a case end to end.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through a pair of mandatory HTTP headers. Each request must include `X-User-ID` to identify the acting operator and `X-User-Role` to specify their operational capacity. The system recognizes seven roles: `PlatformAdmin`, `IntakeSpecialist`, `CaseAnalyst`, `MedicalDirector`, `MemberServicesRep`, `ComplianceOfficer`, and `ClaimsProcessor`. A request whose headers are missing or whose role is not one of these seven is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A well-authenticated request whose role is not permitted to call the target endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

All seven roles — `PlatformAdmin`, `IntakeSpecialist`, `CaseAnalyst`, `MedicalDirector`, `MemberServicesRep`, `ComplianceOfficer`, and `ClaimsProcessor` — carry an opaque identity. When `X-User-Role` names any of them, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it (for example, as `actor_id` on appended case events, or as the `reviewer_physician_id` chosen at clinical-review assignment time) but it does not compare it to any entity's `id`. Segregation-of-duties checks compare one operator's `X-User-ID` against another's, never against a stored foreign key.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return. If not provided, it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order. Two listings define their own order: a case's event log replays in `occurred_at` ascending order with `created_at` ascending as the tie-break, and an audit-universe snapshot captures its rows in decision-time order (see §3.9). Wherever the pinned sort keys compare equal — whether under the default creation-timestamp order or either custom order — records created earlier precede records created later; creation order is the final tie-break, never `id`.

Paginated list responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. The Logical Server Clock

Every deadline, every overdue evaluation, and every temporal window in this system reads a logical server clock — never wall-clock time. Before any operator call to the clock-setting capability, the logical clock reads exactly `2026-08-01T00:00:00Z`; this is the mandatory startup default, and the clock never falls back to wall-clock time thereafter. A `PlatformAdmin` may set the clock by supplying a `to_iso8601` instant; the response reports the resulting `current_utc`.

Setting the clock is not a passive act. All subsequent deadline and overdue evaluations use the new clock value, any Effectuation still `IN_PROGRESS` whose parent case's `effectuation_due_at` is now in the past transitions to `OVERDUE`, and every case's `overdue` flag recomputes against the new present.

### 2.5. Common Resource Properties

All primary resources — Members, Providers, Deadline Policies, Grievance/Appeal Cases, Clinical Reviews, Notifications, IRE Referrals, Effectuations, and Reopenings — carry a standard set of system-managed fields:

- **`id` (string):** A unique, server-minted identifier formatted as a UUID, with no type prefix.
- **`created_at` (string):** An ISO 8601 UTC timestamp with three fractional digits recording when the resource was first created.
- **`updated_at` (string):** An ISO 8601 UTC timestamp refreshed upon any mutation of the resource, including recomputation of derived fields and cascade-driven changes.
- **`version` (integer):** A system-managed integer that increments with every modification to the resource — including appends to its event log and automatic state reconciliations — and serves as the basis for optimistic concurrency control where §2.7 applies.

Two resources are append-only snapshots and deliberately carry less. A `CaseEvent` and an `AuditUniverseRecord` each receive an `id` and a `created_at` and nothing more: both `updated_at` and `version` are absent on these two resources.

Every timestamp the API emits is serialized in one uniform way: an ISO 8601 UTC rendering with exactly three fractional digits and a `Z` designator, so a whole-second instant emits `.000` (for example, `2026-08-02T12:00:00.000Z`). This covers the envelope's `api_request_timestamp`, the clock endpoint's `current_utc`, and every resource timestamp, including `created_at`, `updated_at`, and each workflow stamp (`received_at`, `acknowledged_at`, `decided_at`, `notified_at`, `closed_at`, `resolution_due_at`, `effectuation_due_at`, `occurred_at`, `sent_at`, `forwarded_at`, `ire_decision_received_at`, `completed_at`, `requested_at`, and `snapshot_at`).

### 2.6. Precision, Rounding, and Monetary Representation

Regulatory arithmetic must be reproducible to the cent and to the second.

- **Scores and percentages** are stored at exactly 2 decimal places using round-half-up. The `medical_necessity_score` lies between 0.00 and 100.00; a notification's `completeness_score` lies between 0.00 and 1.00; an effectuation's `timeliness_percent` lies between 0.00 and 100.00 when timely and exceeds 100.00 when late.
- **Rounding order is pinned per calculation and differs deliberately between them.** The medical necessity score rounds once, after the weighted sum is complete (sum-then-round; never per-term). The notification completeness score does the opposite: each matched element's contribution is rounded to 4 decimal places first, the contributions are then summed, and only the total is rounded half-up to 2 decimals (per-element-then-sum).
- **Payment amounts** are integer cents: `payment_amount_cents` must be greater than or equal to zero, with zero denoting a service-only effectuation.
- **Deadline timestamps** are computed and compared to the second, with no rounding applied.

### 2.7. Optimistic Concurrency Control

Three write operations are guarded by optimistic concurrency control, each keyed to the current `version` of a parent resource:

1. Applying the single member-requested extension to a case requires the request to carry `expected_case_version` equal to the case's current `version`. If another writer has advanced the case's version since the client last read it — through triage, an expedite, or an event append — the extension is rejected with `ERR_STALE_VERSION` (HTTP 412), because the extension mutates `resolution_due_at` on a case aggregate the client has not observed.
2. Granting a reopening requires the request to carry `expected_case_version` equal to the source case's current `version`. A grant spawns a replacement case and flips the source case to `REOPENED`; if the source case's version has advanced since the client last read it, the grant is rejected with `ERR_STALE_VERSION` (HTTP 412).
3. Completing an effectuation requires the request to carry `expected_effectuation_version` equal to the effectuation's current `version`. Completion fires the referral auto-transition and the timeliness computation; a client whose view predates a system-driven `OVERDUE` transition (which itself bumps the version) is completing from a stale view and is rejected with `ERR_STALE_VERSION` (HTTP 412).

No other endpoint accepts a version field.

### 2.8. Request Validation Discipline and Error Ordering

Every request is checked against a fixed, prioritized validation sequence, and an earlier failure masks every later one. First, authentication: missing or invalid `X-User-Role` / `X-User-ID` headers are rejected with `ERR_UNAUTHENTICATED`. Second, authorization: a role outside the endpoint's permitted list is rejected with `ERR_UNAUTHORIZED`. Third, path-identifier existence, validated left to right along the URL: the first identifier that does not correspond to an existing row — whether case, notification, clinical review, IRE referral, effectuation, reopening, member, or provider — is rejected with `ERR_NOT_FOUND` (HTTP 404) before any deeper identifier is examined. Fourth, body references: any foreign key supplied in the payload (`member_id`, `provider_id`, `case_id`, `referral_id`, `reopened_from_case_id`) that points at a missing row is rejected with `ERR_REFERENCE_NOT_FOUND` (HTTP 422).

Fifth, transition validity: if the requested action is not declared from the resource's current state, the request is rejected with `ERR_INVALID_STATE` (HTTP 409). Sixth, terminal-state lockdown: any mutation attempted on a resource already in a terminal state is rejected with `ERR_ALREADY_TERMINAL` (HTTP 409). Terminal states are `CLOSED` and `WITHDRAWN` for cases (with the sole exception that a reopening may still be requested against a `CLOSED` case), `DETERMINED` and `SUPERSEDED` for clinical reviews, `DELIVERED` and `FAILED` for notifications (with the sole exception that a `FAILED` notification may be retried), `EFFECTUATED` and `WAIVED` for effectuations, and `GRANTED` and `DENIED` for reopenings.

Only after those six generic gates do endpoint-specific business rules apply, and they too have a fixed relative order: segregation of duties (`ERR_DUTY_SEGREGATION`); clinical routing (`ERR_CLINICAL_REVIEW_REQUIRED`); the three temporal windows — acknowledgement (`ERR_ACK_WINDOW_MISSED`), IRE forwarding (`ERR_IRE_WINDOW_MISSED`), and reopening (`ERR_REOPEN_WINDOW_MISSED`); the one-live-clinical-review constraint (`ERR_REVIEW_IN_FLIGHT`); the single-extension constraint (`ERR_EXTENSION_CONSUMED`); expedited eligibility (`ERR_EXPEDITED_NOT_ALLOWED`); policy configuration (`ERR_POLICY_NOT_CONFIGURED`); notification completeness (`ERR_NOTIFICATION_INCOMPLETE`); the W-9 payment gate (`ERR_W9_REQUIRED`); the waiver gate (`ERR_WAIVER_NOT_ALLOWED`); the payment allowance rule (`ERR_PAYMENT_NOT_ALLOWED`); and finally the duplicate-intake guard (`ERR_DUPLICATE_CASE`). A malformed payload — a missing required field, a wrong type, or an enum value outside its declared constraints — is rejected with `ERR_VALIDATION` (HTTP 400).

### 2.9. Deadline Policy Administration

All timeframe math is driven by Deadline Policy rows, each keyed to a triple of `program`, `case_kind`, and `priority_track`. A policy's `resolution_hours` must be greater than 0 and at most 720 — no resolution clock may exceed thirty days. Its `extension_hours` defaults to 0 and may range up to and including 336 — at most fourteen extra days for a member-requested extension. Its `effectuation_hours` must likewise be greater than 0 and at most 720. The `business_hours_only` flag defaults to `false` and selects a variant of the effectuation timeliness calculation described in §3.7. The `active` flag defaults to `true`.

Uniqueness is enforced on the active policy per triple: only one policy for a given (`program`, `case_kind`, `priority_track`) may have `active` set to `true` at any time, and creating a new active policy for a triple deactivates whichever policy was previously active for it. Policies may be listed with filters on `program`, `case_kind`, `priority_track`, and `active`. Triage and priority upgrades both require exactly one active policy for the case's triple; its absence is rejected with `ERR_POLICY_NOT_CONFIGURED`.

### 2.10. Segregation of Duties

Two independence invariants run through the clinical half of the workflow. The `MedicalDirector` who records the decision on a case sitting in `PENDING_CLINICAL` must not be the same operator — compared by `X-User-ID` — as the `IntakeSpecialist` who triaged that case. And when a clinical review is assigned, the named `reviewer_physician_id` must belong to an operator acting in the `MedicalDirector` role whose `X-User-ID` differs from the `CaseAnalyst` who requested the review; self-assignment is forbidden. Either violation is rejected with `ERR_DUTY_SEGREGATION` (HTTP 422).

## 3. Business Logic & Workflows

### 3.1. Reference Data: Members, Providers, and Policies

Before any case can move, a `PlatformAdmin` seeds the reference data the workflow depends on. A member is registered with a `member_ref` — the plan-internal member identifier, such as a HICN or MBI surrogate — which must be unique across the plan, non-empty, and between 1 and 64 characters; a `full_name` used in notifications; and a `program`, one of `MEDICARE`, `MEDI_CAL`, or `DUAL`. The member's `enrollment_status` is system-managed, begins as `ACTIVE`, and may move to `DISENROLLED` or `DECEASED` over the life of the record. Two counters are computed rather than stored by clients: `open_case_count`, the number of the member's cases whose `status` is any of `RECEIVED`, `TRIAGED`, `IN_REVIEW`, `PENDING_CLINICAL`, `DECIDED`, `NOTIFIED`, `IRE_REFERRED`, or `REOPENED`; and `ctm_linked_case_count`, the number of the member's CTM-linked cases not yet in `CLOSED` or `WITHDRAWN`. The member listing accepts an optional `program` filter, and a member's cases are reachable as a collection accepting an optional `status` filter.

A provider is registered with an `npi` — exactly 10 digits and unique — a `legal_name`, a `contract_status` of `CONTRACTED` or `NON_CONTRACTED`, and a `w9_on_file` flag that defaults to `false`. The W-9 flag is not decorative: the plan may not release a payment effectuation to a provider without one on file (§3.7). A `PlatformAdmin` may later patch a provider's `w9_on_file` and `contract_status`; each patch increments the provider's `version`.

Deadline policies are administered per §2.9. Together these three reference sets — member, provider, policy — determine whether any given case can be triaged, decided, paid, and closed.

### 3.2. Case Intake, Classification, and Early Withdrawal

An `IntakeSpecialist` opens a case by supplying the `member_id` of the owning member, a `case_kind` of `GRIEVANCE`, `ORG_DETERMINATION`, or `APPEAL`, and optionally a `provider_id` naming the rendering provider or provider of record. The provider reference is nullable only for pure grievances; organization determinations and appeals arise from service denials and therefore always carry a provider, a fact enforced at triage. Intake also accepts `expedited_requested` (default `false`) with an accompanying `expedited_justification` whenever the requester asked for expedited handling — the justification must be non-empty free text describing the clinical urgency, and omitting it while requesting expedition renders the payload invalid. An optional `reopened_from_case_id` records self-referential lineage when the case being intaken is the product of a granted reopening of an earlier closed case (§3.8).

The server stamps `received_at` at intake, sets `status` to `RECEIVED`, and increments the member's `open_case_count` by one. Two guards fire at this door. The duplicate-intake guard rejects a new case when an identical case — same `member_id`, same `case_kind`, same `provider_id` — was received within the prior one hour and is still in a non-terminal state; the rejection is `ERR_DUPLICATE_CASE` (HTTP 409). And because grievances have no expedited track, an intake that sets `expedited_requested` on a `GRIEVANCE` is rejected with `ERR_EXPEDITED_NOT_ALLOWED`. The case listing supports filters on `member_id`, `provider_id`, `status`, `case_kind`, `priority_track`, `overdue`, and `reopened_from_case_id`.

Withdrawal is available early and only early. A `MemberServicesRep` may withdraw a case while it sits in `RECEIVED`, `TRIAGED`, or `IN_REVIEW` — that is, only before clinical engagement. Withdrawal moves the case to `WITHDRAWN`, stamps `closed_at`, decrements the member's `open_case_count` by one (and `ctm_linked_case_count` as well when the case was CTM-linked), and appends a `NOTE` event whose `body` reads `WITHDRAWN`, incrementing the case's `version`.

### 3.3. Triage, Resolution Deadlines, Extensions, and Expedited Upgrades

Triage is the moment a raw intake becomes a regulated obligation. An `IntakeSpecialist` triages a case in `RECEIVED`, and four preconditions stand in front of the transition. The case's member must be `ACTIVE`. For an `ORG_DETERMINATION` or `APPEAL`, the `provider_id` must reference an existing Provider. When `expedited_requested` is true, the justification must have been captured at intake and an active Deadline Policy must exist for the member's program, the case kind, and the `EXPEDITED` track — otherwise `ERR_POLICY_NOT_CONFIGURED`. And the acknowledgement window is enforced: triage attempted more than 24 hours after `received_at` is rejected with `ERR_ACK_WINDOW_MISSED`.

Triage classifies the case's `priority_track`: it becomes `EXPEDITED` when the requester asked for expedition and the case kind is not `GRIEVANCE`, and `STANDARD` otherwise. The server stamps `acknowledged_at`, computes `resolution_due_at`, appends a `NOTE` event whose `body` reads `TRIAGED`, and increments the case's `version`. The deadline computation anchors at `received_at` and adds the active policy's `resolution_hours` for the case's (`program`, `case_kind`, `priority_track`) triple; when an extension has been applied, the policy's `extension_hours` are added on top. Independently of where the deadline lands, a case whose acknowledgement ran past the 24-hour window is flagged acknowledgement-late; the flag never moves `resolution_due_at`, but the compliance-attribution view of the audit universe (§3.9) reads it. A case's `overdue` flag is true whenever the current time is past `resolution_due_at` while the case's `status` is anything other than `CLOSED`, `WITHDRAWN`, or `IRE_REFERRED`.

From `TRIAGED`, a `CaseAnalyst` begins review, moving the case to `IN_REVIEW` and appending a `NOTE` event whose `body` reads `REVIEW_STARTED`.

Two in-place adjustments can reshape the clock while work proceeds, and both are cyclic self-transitions that leave the case in its current state. The member-requested extension, applied by a `MemberServicesRep` from `TRIAGED`, `IN_REVIEW`, or `PENDING_CLINICAL`, consumes the case's single extension allowance: it is permitted only while `extension_applied` is `false` and the governing policy grants `extension_hours` greater than zero — otherwise `ERR_EXTENSION_CONSUMED`. The request must carry `expected_case_version` per §2.7, and a stale version is rejected with `ERR_STALE_VERSION`. Granting sets `extension_applied` to `true`, recomputes `resolution_due_at` as the previously computed deadline plus the policy's extension hours, appends an `EXTENSION_GRANTED` event, and increments the case's `version`.

The expedited upgrade, performed by a `MedicalDirector` from `TRIAGED` or `IN_REVIEW`, tightens the clock rather than loosening it. It requires the case's `priority_track` to still be `STANDARD`, the case kind to be anything other than `GRIEVANCE` (a grievance can never be expedited — `ERR_EXPEDITED_NOT_ALLOWED`), and an active `EXPEDITED` policy for the case's triple (`ERR_POLICY_NOT_CONFIGURED`). The upgrade sets `priority_track` to `EXPEDITED` and recomputes `resolution_due_at` under the expedited policy's smaller `resolution_hours` — crucially, the anchor remains the original `received_at`, not the moment of the upgrade, so a mid-flight upgrade shortens the remaining window rather than restarting it. A `PRIORITY_UPGRADE` event is appended and the case's `version` increments.

### 3.4. Clinical Review and the Medical Necessity Score

When an analyst judges that a case in `IN_REVIEW` needs physician review, the `CaseAnalyst` requests a clinical review; the case moves to `PENDING_CLINICAL` and a Clinical Review is created in `REQUESTED` status, with a `NOTE` event whose `body` reads `CLINICAL_REVIEW_REQUESTED` appended to the case. A replacement review may also be requested while the case is already in `PENDING_CLINICAL` — for example after a prior review reached a terminal state — but only one live review may exist per case at any moment: if any review for the case currently sits in `REQUESTED`, `ASSIGNED`, or `DETERMINATION_DRAFT`, the request is rejected with `ERR_REVIEW_IN_FLIGHT` (HTTP 409). Either way the case's `version` increments.

Assignment turns the request into a named obligation. A `MedicalDirector` assigns the review by supplying `reviewer_physician_id`; per §2.10 the named physician must act as a `MedicalDirector` and must not be the requesting analyst, or the assignment is rejected with `ERR_DUTY_SEGREGATION`. The review moves `REQUESTED` → `ASSIGNED` and its `version` increments. From that point on, only the assignee may touch the clinical substance: both drafting and finalizing require the caller's `X-User-ID` to equal the review's `reviewer_physician_id`.

Drafting the determination moves the review `ASSIGNED` → `DETERMINATION_DRAFT` and triggers the medical necessity score. The draft payload carries five clinical factor integers — `severity`, `acuity`, `guideline_match`, `comorbidity`, and `functional_impairment` — each between 0 and 10 inclusive. The weighted raw score takes 35 percent of `severity`, 25 percent of `acuity`, 20 percent of `guideline_match`, 10 percent of `comorbidity`, and 10 percent of `functional_impairment`; that sum is multiplied by ten and rounded half-up to two decimal places exactly once, after the summation, producing the `medical_necessity_score` between 0.00 and 100.00. A physician override exists for the exceptional case: when the draft payload includes `override_score`, the stored `medical_necessity_score` is the override value rounded half-up to two decimals and clamped to the range from 0.00 to 100.00; the weighted formula result is retained in the draft's audit body even though the override is what gets stored.

Finalization moves the review `DETERMINATION_DRAFT` → `DETERMINED` and records the `determination` payload, one of `UPHOLD_SERVICE`, `OVERTURN_SERVICE`, or `PARTIAL`. A determined review is terminal with one systemic exception: when a newer clinical review is created for the same case after a reopening, the prior `DETERMINED` review is marked `SUPERSEDED`, and its `superseded_by_review_id` points at the newer review's `id`. Reviews are listable with filters on `case_id`, `status`, and `superseded_by_review_id`.

### 3.5. The Decision and Member Notification

A decision lands through one of two doors, and the doors are segregated by case kind. The clinical door: a `MedicalDirector` decides a case in `PENDING_CLINICAL`, which requires a Clinical Review for the case to already sit in `DETERMINED` status and requires, per §2.10, that the deciding physician not be the intake specialist who triaged the case. The non-clinical door: a `CaseAnalyst` decides a case directly from `IN_REVIEW`, which is permitted only when the `case_kind` is `GRIEVANCE` — an organization determination or appeal decided without clinical review is rejected with `ERR_CLINICAL_REVIEW_REQUIRED`.

Either door takes a `decision_outcome` of `FULLY_FAVORABLE`, `PARTIALLY_FAVORABLE`, or `UNFAVORABLE`, plus an optional `payment_amount_cents`. Recording the decision sets `decision_outcome`, stamps `decided_at`, moves the case to `DECIDED`, appends a `DECISION_RECORDED` event, and increments the case's `version`. When the outcome is anything other than `UNFAVORABLE`, the decision simultaneously arms effectuation: `effectuation_due_at` is computed as `decided_at` plus the active policy's `effectuation_hours`, and an Effectuation is created in `PENDING` status with `payment_amount_cents` taken from the decision payload. An `UNFAVORABLE` outcome carries no such obligation — `effectuation_due_at` stays null and no effectuation is created — and fiscal discipline bars payment in that direction: `payment_amount_cents` must never be negative, and supplying a payment alongside an `UNFAVORABLE` outcome is rejected with `ERR_PAYMENT_NOT_ALLOWED`.

A decision is not complete until the member has been told, in writing, with all federally required content. Notification authoring is a `MemberServicesRep` duty: each notification names the parent `case_id` through the case it is created against, a `recipient_kind` of `MEMBER` or `PROVIDER`, a `notification_kind` drawn from `ACKNOWLEDGEMENT`, `EXTENSION_NOTICE`, `DECISION`, `IRE_FORWARD_NOTICE`, `REOPEN_OUTCOME`, or `EFFECTUATION_CONFIRMATION`, and the `supplied_elements` actually present in the rendered notice body. The server resolves `required_elements` from the notification content matrix keyed by the tuple of notification kind, recipient kind, the member's program, the case kind, and the decision outcome, and computes the `completeness_score` on creation and again whenever the representative patches `supplied_elements` — a patch permitted only while the notification is still `QUEUED`. Each required element carries a fixed weight: `citation_of_criteria` at 0.25, `appeal_rights` at 0.25, `decision_rationale` at 0.20, `expedited_availability` at 0.10, `ire_notice` at 0.10, `contact_information` at 0.05, and `language_assistance` at 0.05, the weights summing to exactly 1.00. Per the pinned per-element-then-sum order of §2.6, each matched element's contribution is rounded to four decimals, the contributions are summed, and the total is rounded half-up to two decimals.

Delivery is its own small lifecycle. A `QUEUED` notification is marked sent only when its `completeness_score` is exactly 1.00 — every required element supplied — else `ERR_NOTIFICATION_INCOMPLETE`; the first transition into `SENT` stamps `sent_at`. From `SENT`, the notice may be marked `DELIVERED` or may be marked `FAILED`; a `FAILED` notice may be retried into `RETRIED`, and a retried notice is marked sent into `SENT` again under the same completeness gate. The transition with regulatory teeth is the member's decision letter: when the `DECISION` notification addressed to the `MEMBER` reaches `SENT`, the parent case auto-transitions `DECIDED` → `NOTIFIED`, the case's `notified_at` takes the notification's `sent_at`, a `NOTIFICATION_SENT` event is appended, and the case's `version` increments. Case notifications are listable with `status` and `notification_kind` filters.

### 3.6. Independent Review Entity Referral

Adverse appeal outcomes earn the member an external review. A `ComplianceOfficer` forwards a `NOTIFIED` case to the IRE by supplying the `ire_organization_code` of the contracted independent review organization — but only for an `APPEAL` whose `decision_outcome` is not `FULLY_FAVORABLE`, since fully favorable outcomes leave nothing to dispute externally, and only within 72 hours of `decided_at` — the window's boundary is inclusive, so a forwarding attempted at exactly 72 hours after `decided_at` is still within it, and only a forwarding attempted later than that is rejected with `ERR_IRE_WINDOW_MISSED`. Forwarding moves the case `NOTIFIED` → `IRE_REFERRED`, creates the referral in `FORWARDED` status with `forwarded_at` stamped by the server, appends an `IRE_FORWARDED` event, and increments the case's `version`.

The referral then walks its own lifecycle. Recording the IRE's acknowledgement moves it `FORWARDED` → `ACKNOWLEDGED_BY_IRE`. Recording the IRE's decision — an `ire_decision` payload of `UPHOLD_PLAN`, `OVERTURN_PLAN`, or `PARTIAL`, optionally accompanied by `payment_amount_cents` — moves it `ACKNOWLEDGED_BY_IRE` → `DECISION_RECEIVED` and stamps `ire_decision_received_at`. When the IRE overturns the plan in whole or in part, the recording simultaneously creates an Effectuation on the parent case in `PENDING` status whose `referral_id` points back to this referral; an `UPHOLD_PLAN` outcome creates nothing. Later, when that linked effectuation completes, the referral auto-transitions `DECISION_RECEIVED` → `EFFECTUATED`. An `UPHOLD_PLAN` referral never takes that final step — the case closes with the referral resting at `DECISION_RECEIVED`.

### 3.7. Effectuation Execution and Timeliness Measurement

Effectuation is where the plan pays or performs what it now owes. A `ClaimsProcessor` starts a `PENDING` effectuation, moving it to `IN_PROGRESS` and appending an `EFFECTUATION_STARTED` event on the parent case. The W-9 gate stands in front of any monetary release: when `payment_amount_cents` is greater than zero and the case's `provider_id` references a Provider, that provider's `w9_on_file` must be `true`, or the start is rejected with `ERR_W9_REQUIRED`.

Completion is permitted from `IN_PROGRESS`, `OVERDUE`, or `ESCALATED` and is guarded per §2.7: the request must carry `expected_effectuation_version` matching the effectuation's current `version`, else `ERR_STALE_VERSION`. Completing stamps `completed_at`, computes `timeliness_percent`, appends an `EFFECTUATION_COMPLETED` event on the parent case, and — when the effectuation's `referral_id` is set — fires the linked referral's auto-transition to `EFFECTUATED`. The timeliness percentage measures window consumption: one hundred times the consumed hours divided by the window hours, where the window runs from the case's `decided_at` to its `effectuation_due_at` and the consumed hours run from `decided_at` to the effectuation's `completed_at`, the result rounded half-up to two decimal places. The timeliness boundary is inclusive: a consumed interval exactly equal to the window yields 100.00 and is timely, while 100.01 is late — any completion after `effectuation_due_at` produces a value above 100.00.

Time itself moves effectuations. When the logical clock passes the parent case's `effectuation_due_at` while an effectuation is `IN_PROGRESS`, the system transitions it to `OVERDUE` (clock advances per §2.4 perform this sweep). A `ComplianceOfficer` may escalate an `OVERDUE` effectuation into `ESCALATED`, and completion remains available from there. One calculation variant matters for Medi-Cal service-only work: when the governing Deadline Policy carries `business_hours_only` set to `true`, the consumed hours count only Monday-through-Friday 08:00–17:00 UTC hours, so the same wall-clock interval yields a smaller `timeliness_percent` than the default calendar-hours variant.

A `ComplianceOfficer` may waive an effectuation outright, but only a service-only one: the waiver moves `PENDING` → `WAIVED` and requires `payment_amount_cents` to be exactly zero, else `ERR_WAIVER_NOT_ALLOWED`. Effectuations are listable with filters on `case_id`, `referral_id`, and `status`.

### 3.8. Case Closure and Reopening

Closure is a `ComplianceOfficer` act with preconditions that depend on how the case ended. Closing from `NOTIFIED` requires, when the outcome was not `UNFAVORABLE`, that the linked effectuation already be `EFFECTUATED` or `WAIVED`; and when the outcome was not `FULLY_FAVORABLE` and the case is an `APPEAL`, that either an IRE referral exists or the 72-hour forwarding window lapsed unexercised — the window lapses only once the current time is strictly past `decided_at` plus 72 hours, so at exactly that instant the lapse ground is not yet available — the lapse documented by a `NOTE` event on the case. Closing from `IRE_REFERRED` requires the linked referral to be `DECISION_RECEIVED`, and when the `ire_decision` was `OVERTURN_PLAN` or `PARTIAL`, that the linked effectuation be `EFFECTUATED`. Either closure stamps `closed_at`, decrements the member's `open_case_count` by one (and `ctm_linked_case_count` when the case was CTM-linked), appends a `NOTE` event whose `body` reads `CLOSED`, and increments the case's `version`.

A closed case is not necessarily a finished case. A `ComplianceOfficer` or a `MemberServicesRep` may request a reopening against a `CLOSED` case by supplying the `case_id` and a `request_reason` of `NEW_EVIDENCE`, `CLERICAL_ERROR`, or `FRAUD_OR_SIMILAR_FAULT`; the request stamps `requested_at` and appends a `REOPEN_REQUESTED` event on the source case. The reopening window is measured from the source case's `closed_at`: `NEW_EVIDENCE` and `CLERICAL_ERROR` requests must arrive within 180 days of closure, while `FRAUD_OR_SIMILAR_FAULT` is exempt from any window — a request outside its window is rejected with `ERR_REOPEN_WINDOW_MISSED`. A `ComplianceOfficer` then begins review, moving the reopening `REQUESTED` → `UNDER_REVIEW`.

Adjudication has two exits. Denial moves `UNDER_REVIEW` → `DENIED`, stamps the reopening's `decided_at`, and appends a `REOPEN_DENIED` event on the source case. Granting is the heavier act: the same 180-day-or-exempt window is re-verified between the source case's `closed_at` and the reopening's `requested_at`, no other reopening for the same case may already be `GRANTED`, and the request must carry `expected_case_version` matching the source case's current `version` per §2.7, else `ERR_STALE_VERSION`. On grant, the reopening's `decided_at` is stamped and its `spawned_case_id` is set to a newly created case — status `RECEIVED`, `reopened_from_case_id` pointing at the source case, `case_kind` and `priority_track` copied from it — while the source case auto-transitions `CLOSED` → `REOPENED` as a marker, the member's `open_case_count` increments by one for the spawned case, any `DETERMINED` clinical review on the source case transitions to `SUPERSEDED`, and a `REOPEN_GRANTED` event is appended on the source case. The marker unwinds itself: when the spawned replacement case eventually reaches `CLOSED`, the source case auto-transitions `REOPENED` → `CLOSED` and its `closed_at` is overwritten with that moment. Reopenings against a case are listable with a `status` filter.

### 3.9. Complaint Tracking, the Audit Universe, and Compliance Reporting

Every case carries an append-only event log. Staff in the `IntakeSpecialist`, `CaseAnalyst`, `MemberServicesRep`, and `ComplianceOfficer` roles may append events with an `event_type` of `NOTE`, `DOCUMENT`, `EXTENSION_REQUEST`, `CTM_LINKED`, or `CTM_UNLINKED` and an optional free-text `body`; the server stamps `occurred_at` and captures `actor_role` and `actor_id` from the request headers at append time, and every append increments the parent case's `version` by one. The remaining event types — `EXTENSION_GRANTED`, `PRIORITY_UPGRADE`, `DECISION_RECORDED`, `NOTIFICATION_SENT`, `IRE_FORWARDED`, `REOPEN_REQUESTED`, `REOPEN_GRANTED`, `REOPEN_DENIED`, `EFFECTUATION_STARTED`, and `EFFECTUATION_COMPLETED` — are appended by the workflows themselves as transitions fire. The log replays in `occurred_at` ascending order with `created_at` ascending as the tie-break, and accepts an `event_type` filter.

Two of the appendable event types drive the Complaint Tracking Module linkage. Appending a `CTM_LINKED` event sets the case's `ctm_linked` flag to true and increments the member's `ctm_linked_case_count` by one, provided the case is not `CLOSED` or `WITHDRAWN`; appending `CTM_UNLINKED` clears the flag and decrements the count by one, never below zero and only when the case was previously linked. The member's CTM exposure tier derives from that count: zero linked cases is tier `NONE` with weight 0; one or two is `LOW` with weight 1; three to five is `MEDIUM` with weight 2; six or more is `HIGH` with weight 3 — so a count of exactly three is `MEDIUM` and exactly six is `HIGH`. The member's CTM exposure view returns the `tier`, the `weight`, the `provisional_weight`, and the raw `ctm_linked_case_count`. Provisional weighting handles the pre-classification window: a case linked while still in `RECEIVED` — before triage confirms its classification — counts at half weight, 0.5, and the tier thresholds then compare against the ceiling of the total provisional weight; after triage the identical link counts at full weight, so the same data can yield a different tier before and after triage.

The audit universe is the artifact regulators actually sample. A `ComplianceOfficer` builds it for a `report_period` keyed in `YYYY-MM` form; the snapshot includes every case whose `decided_at` falls inside the half-open period window — inclusive of the period's first instant, exclusive of the next period's first instant — and cases that were never decided are excluded entirely. Rows are captured in deterministic order: `decided_at` ascending, then `created_at` ascending, never by `id`. Each resulting Audit Universe Record denormalizes the case's `case_kind` and `priority_track` at snapshot time, stamps `snapshot_at`, and records two booleans: `resolution_timely`, true when `decided_at` was on or before `resolution_due_at` — equality is timely — and `effectuation_timely`, true when the linked effectuation's `completed_at` was on or before the case's `effectuation_due_at`, and null when no effectuation was required. The uniqueness scope is the pair of `report_period` and `case_id`: re-running a snapshot that would recapture a pair already recorded is rejected with `ERR_DUPLICATE_SNAPSHOT` (HTTP 409). The snapshot response reports the `report_period` and the number of `rows_created`, and the universe listing filters by `report_period`, `case_id`, `case_kind`, `priority_track`, and `resolution_timely`.

Above the raw universe sits the compliance-attribution view. For a `report_period`, it returns `total_cases`, `resolution_timely_count`, `resolution_timely_rate`, `intake_delay_count`, `reviewer_late_count`, and `effectuation_timely_rate`. The attribution rule separates intake lateness from reviewer lateness: a case that missed its resolution deadline solely because its acknowledgement ran past the 24-hour window of §3.3 is attributed to intake delay and excluded from the reviewer-lateness numerator, whereas the raw snapshot variant counts the identical case as simply late — the two views of the same data therefore produce different timeliness rates, deliberately.

## 4. Endpoint Definitions

Operations that create new resources — registering a member, provider, or deadline policy, intaking a case, appending an event, requesting a clinical review, authoring a notification, forwarding to the IRE, requesting a reopening, or building an audit snapshot — return `201 Created`. Operations that act on or modify an existing resource, and all retrievals, return `200 OK`. Request payloads, response payloads, and side effects are defined by the narratives in §3; the table below is the routing and authorization contract.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/appeals/_clock/set_current_utc` | Set the logical server clock | PlatformAdmin |
| POST | `/appeals/members` | Register a member | PlatformAdmin |
| GET | `/appeals/members/{id}` | Fetch one member (with computed counters) | PlatformAdmin, IntakeSpecialist, CaseAnalyst, MedicalDirector, MemberServicesRep, ComplianceOfficer, ClaimsProcessor |
| GET | `/appeals/members` | List members; optional `program` filter | PlatformAdmin, ComplianceOfficer |
| GET | `/appeals/members/{id}/ctm-exposure` | Computed CTM exposure tier for a member | PlatformAdmin, ComplianceOfficer, MemberServicesRep |
| GET | `/appeals/members/{id}/cases` | List all cases for a member | PlatformAdmin, IntakeSpecialist, CaseAnalyst, ComplianceOfficer, MemberServicesRep |
| POST | `/appeals/providers` | Register a provider | PlatformAdmin |
| GET | `/appeals/providers/{id}` | Fetch one provider | PlatformAdmin, IntakeSpecialist, CaseAnalyst, ComplianceOfficer, ClaimsProcessor |
| PATCH | `/appeals/providers/{id}` | Update provider `w9_on_file` / `contract_status` | PlatformAdmin |
| POST | `/appeals/deadline-policies` | Create a deadline policy (active uniqueness per triple) | PlatformAdmin |
| GET | `/appeals/deadline-policies` | List policies with filters | PlatformAdmin, ComplianceOfficer |
| POST | `/appeals/cases` | Intake a grievance / organization determination / appeal | IntakeSpecialist |
| GET | `/appeals/cases/{id}` | Fetch one case | PlatformAdmin, IntakeSpecialist, CaseAnalyst, MedicalDirector, MemberServicesRep, ComplianceOfficer, ClaimsProcessor |
| GET | `/appeals/cases` | List cases with filters and pagination | PlatformAdmin, ComplianceOfficer, CaseAnalyst |
| POST | `/appeals/cases/{id}/triage` | Triage a `RECEIVED` case; classify track, compute deadline | IntakeSpecialist |
| POST | `/appeals/cases/{id}/begin-review` | Move a `TRIAGED` case into analyst review | CaseAnalyst |
| POST | `/appeals/cases/{id}/expedite` | Upgrade `STANDARD` to `EXPEDITED` in place | MedicalDirector |
| POST | `/appeals/cases/{id}/extensions` | Apply the single member-requested extension (OCC-guarded) | MemberServicesRep |
| POST | `/appeals/cases/{id}/decide` | Record the decision (outcome + optional payment) | MedicalDirector, CaseAnalyst |
| POST | `/appeals/cases/{id}/withdraw` | Withdraw a pre-clinical case | MemberServicesRep |
| POST | `/appeals/cases/{id}/close` | Close a `NOTIFIED` or `IRE_REFERRED` case | ComplianceOfficer |
| GET | `/appeals/cases/{id}/events` | Chronological event log for a case | PlatformAdmin, IntakeSpecialist, CaseAnalyst, MedicalDirector, MemberServicesRep, ComplianceOfficer |
| GET | `/appeals/cases/{id}/clinical-reviews` | List clinical reviews for a case | PlatformAdmin, CaseAnalyst, MedicalDirector, ComplianceOfficer |
| GET | `/appeals/cases/{id}/notifications` | List notifications for a case | PlatformAdmin, MemberServicesRep, ComplianceOfficer |
| GET | `/appeals/cases/{id}/ire-referrals` | List IRE referrals for a case | PlatformAdmin, ComplianceOfficer |
| GET | `/appeals/cases/{id}/effectuations` | List effectuations for a case | PlatformAdmin, ComplianceOfficer, ClaimsProcessor |
| GET | `/appeals/cases/{id}/reopenings` | List reopenings against a case | PlatformAdmin, ComplianceOfficer |
| POST | `/appeals/cases/{id}/events` | Append an event (NOTE, DOCUMENT, EXTENSION_REQUEST, CTM_LINKED, CTM_UNLINKED) | IntakeSpecialist, CaseAnalyst, MemberServicesRep, ComplianceOfficer |
| POST | `/appeals/cases/{id}/clinical-reviews` | Request a clinical review (case enters `PENDING_CLINICAL`) | CaseAnalyst |
| GET | `/appeals/clinical-reviews/{id}` | Fetch one clinical review | PlatformAdmin, CaseAnalyst, MedicalDirector, ComplianceOfficer |
| GET | `/appeals/clinical-reviews` | List clinical reviews with filters | PlatformAdmin, CaseAnalyst, MedicalDirector, ComplianceOfficer |
| POST | `/appeals/clinical-reviews/{id}/assign` | Assign a physician reviewer | MedicalDirector |
| POST | `/appeals/clinical-reviews/{id}/draft-determination` | Submit clinical factor scores; compute necessity score | MedicalDirector |
| POST | `/appeals/clinical-reviews/{id}/finalize-determination` | Finalize the determination | MedicalDirector |
| POST | `/appeals/cases/{id}/notifications` | Create a notification for a case | MemberServicesRep |
| GET | `/appeals/notifications/{id}` | Fetch one notification | PlatformAdmin, MemberServicesRep, ComplianceOfficer |
| PATCH | `/appeals/notifications/{id}` | Update `supplied_elements` while `QUEUED` | MemberServicesRep |
| POST | `/appeals/notifications/{id}/mark-sent` | Mark a `QUEUED` or `RETRIED` notification `SENT` | MemberServicesRep |
| POST | `/appeals/notifications/{id}/mark-delivered` | Mark `SENT` → `DELIVERED` | MemberServicesRep |
| POST | `/appeals/notifications/{id}/mark-failed` | Mark `SENT` or `RETRIED` → `FAILED` | MemberServicesRep |
| POST | `/appeals/notifications/{id}/retry` | Retry a `FAILED` notification | MemberServicesRep |
| POST | `/appeals/cases/{id}/ire-referrals` | Forward a `NOTIFIED` adverse appeal to the IRE | ComplianceOfficer |
| GET | `/appeals/ire-referrals/{id}` | Fetch one referral | PlatformAdmin, ComplianceOfficer |
| POST | `/appeals/ire-referrals/{id}/ire-acknowledge` | Record IRE acknowledgement | ComplianceOfficer |
| POST | `/appeals/ire-referrals/{id}/ire-record-decision` | Record the IRE decision; spawns effectuation when overturned/partial | ComplianceOfficer |
| GET | `/appeals/effectuations/{id}` | Fetch one effectuation | PlatformAdmin, ComplianceOfficer, ClaimsProcessor |
| GET | `/appeals/effectuations` | List effectuations with filters | PlatformAdmin, ComplianceOfficer, ClaimsProcessor |
| POST | `/appeals/effectuations/{id}/start` | Begin effectuation (W-9 gate for payments) | ClaimsProcessor |
| POST | `/appeals/effectuations/{id}/complete` | Complete effectuation (OCC-guarded); computes timeliness | ClaimsProcessor |
| POST | `/appeals/effectuations/{id}/waive` | Waive a zero-amount effectuation | ComplianceOfficer |
| POST | `/appeals/effectuations/{id}/escalate` | Escalate an `OVERDUE` effectuation | ComplianceOfficer |
| POST | `/appeals/reopenings` | Request reopening of a `CLOSED` case | ComplianceOfficer, MemberServicesRep |
| GET | `/appeals/reopenings/{id}` | Fetch one reopening | PlatformAdmin, ComplianceOfficer |
| POST | `/appeals/reopenings/{id}/begin-review` | Move reopening `REQUESTED` → `UNDER_REVIEW` | ComplianceOfficer |
| POST | `/appeals/reopenings/{id}/grant` | Grant a reopening (OCC-guarded); spawns replacement case | ComplianceOfficer |
| POST | `/appeals/reopenings/{id}/deny` | Deny a reopening | ComplianceOfficer |
| POST | `/appeals/audit-universe/snapshot` | Build the audit universe for a report period | ComplianceOfficer |
| GET | `/appeals/audit-universe` | List audit universe records with filters | PlatformAdmin, ComplianceOfficer |
| GET | `/appeals/audit-universe/{id}` | Fetch one audit universe record | PlatformAdmin, ComplianceOfficer |
| GET | `/appeals/audit-universe/compliance-summary` | Compliance-attribution aggregation over a report period | PlatformAdmin, ComplianceOfficer |

## 5. Error Code Catalogue

Trigger conditions for each error live in the §2 and §3 narratives; this catalogue is the identifier-to-status mapping only.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_UNAUTHORIZED` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_REFERENCE_NOT_FOUND` | 422 Unprocessable Entity |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_ALREADY_TERMINAL` | 409 Conflict |
| `ERR_DUTY_SEGREGATION` | 422 Unprocessable Entity |
| `ERR_CLINICAL_REVIEW_REQUIRED` | 422 Unprocessable Entity |
| `ERR_ACK_WINDOW_MISSED` | 422 Unprocessable Entity |
| `ERR_IRE_WINDOW_MISSED` | 422 Unprocessable Entity |
| `ERR_REOPEN_WINDOW_MISSED` | 422 Unprocessable Entity |
| `ERR_REVIEW_IN_FLIGHT` | 409 Conflict |
| `ERR_EXTENSION_CONSUMED` | 422 Unprocessable Entity |
| `ERR_EXPEDITED_NOT_ALLOWED` | 422 Unprocessable Entity |
| `ERR_POLICY_NOT_CONFIGURED` | 422 Unprocessable Entity |
| `ERR_NOTIFICATION_INCOMPLETE` | 422 Unprocessable Entity |
| `ERR_W9_REQUIRED` | 422 Unprocessable Entity |
| `ERR_WAIVER_NOT_ALLOWED` | 422 Unprocessable Entity |
| `ERR_PAYMENT_NOT_ALLOWED` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_CASE` | 409 Conflict |
| `ERR_DUPLICATE_SNAPSHOT` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_VALIDATION` | 400 Bad Request |
