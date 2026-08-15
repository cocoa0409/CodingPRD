# Prior Authorization UM API — Product Requirements Document

## 1. Introduction

Health plans and utilization management vendors operate under intense regulatory scrutiny: every prior authorization decision must be defensible against clinical criteria, issued within mandated turnaround windows, and auditable end-to-end. The Prior Authorization UM API is the operational backbone for a utilization management vendor that runs this process on behalf of delegating health plans. It governs the full lifecycle of a prior authorization case — from the moment a request arrives through a portal, fax, phone, or EDI feed, through auto-adjudication against a versioned clinical criteria library, tiered human review by clinical reviewers and medical directors, peer-to-peer conferences, determination notices, and finally appeals whose outcomes feed program-level overturn analysis.

Beyond the per-case pipeline, the platform carries the vendor's compliance posture. A gold-carding program rewards high-performing providers with exemption from routine review, but only while their rolling approval statistics remain healthy. Delegation oversight tracks the vendor's contractual arrangements with delegating health plans: audit findings accumulate against each arrangement, and an arrangement with too many open deficiencies automatically suspends intake for the delegated scope. All of this runs on a server-managed logical clock, so turnaround-time compliance is deterministic and testable rather than hostage to wall-clock drift.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelope contracts, and cross-cutting principles that apply to every endpoint.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring their operational capacity. A request in which either header is missing or empty is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). Once identity is established, the role is checked against the endpoint's permission set; a caller whose role is not permitted is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403).

The system recognizes exactly eight roles, spelled as follows: `UMAdmin`, `ClinicalPolicyEditor`, `IntakeSpecialist`, `ClinicalReviewer`, `MedicalDirector`, `AppealsClerk`, `AppealsReviewer`, and `ComplianceOfficer`.

For all eight roles, `X-User-ID` is an **opaque operator identifier** not tied to any persisted entity — there is no user table to join against. The server nevertheless records the identifier on resources where a transition attributes an actor: the `escalated_by_user_id` of a `PriorAuthRequest` when a `ClinicalReviewer` escalates, the `md_user_id` of a `PeerToPeerConference` when a `MedicalDirector` schedules it, the `reviewer_id` of an `Appeal` when an `AppealsReviewer` begins review, and the `decided_by_user_id` of a `Determination` for human-tier decisions. Segregation-of-duties rules (see §2.8) compare these recorded identifiers against `X-User-ID`; ownership-style checks otherwise do not apply.

Role responsibilities in brief: `UMAdmin` administers the provider registry, delegation arrangements, gold-card evaluations, determination voids, and the logical clock. `ClinicalPolicyEditor` maintains the criteria library — criteria sets and guideline version lifecycles. `IntakeSpecialist` performs request intake and withdrawal. `ClinicalReviewer` is the first clinical decision tier. `MedicalDirector` is the second clinical tier and owns peer-to-peer scheduling. `AppealsClerk` files and withdraws appeals. `AppealsReviewer` reviews and decides appeals. `ComplianceOfficer` records and closes audit findings. All eight roles may use any read endpoint.

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
- The `data` field contains the resource object or an array of resource objects. For 2xx responses with no data, it contains an empty object. Unless otherwise noted, operations that create or modify a resource will return the created or updated resource object in the data field. When one call mutates several resources (an intake that also creates a determination, a decision whose cascades touch related rows), `data` carries the resource the operation is addressed to: the newly created resource for creation endpoints, and the path-addressed resource for the rest — reviewer and medical-director decisions return the updated request, a determination void returns the voided determination, and an appeal decision returns the appeal.
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

Two further failure paths use the same error envelope: a request to an undefined path, or to a defined path with an unsupported method, is rejected with `ERR_NOT_FOUND` (HTTP 404); an unexpected server-side failure surfaces as `ERR_INTERNAL` (HTTP 500).

### 2.3. Pagination

List endpoints paginate through two query parameters. `limit` caps the number of returned items; it defaults to 10, with a minimum of 1 and a maximum of 100. `offset` skips that many items from the front of the result set and defaults to 0. Both are parsed leniently: a non-numeric value falls back to the default, a `limit` below 1 or above 100 is clamped into range, and a negative `offset` is floored to 0 — out-of-range pagination is never an error. Unless otherwise specified, list endpoints return resources sorted by `created_at` in ascending order, with same-instant ties broken by creation order, earliest created first. Every list response carries `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope; `total_count` counts every resource matching the supplied filters before pagination, and `has_more` is true exactly when `offset + limit` is less than `total_count`. Filters are pure equality matches against stored rows: a filter parameter present with an empty value is treated as absent, and an unknown filter value simply yields an empty result rather than an error. A list with zero matching resources returns an empty array in `data`.

### 2.4. Common Resource Properties

Every primary resource carries a server-minted `id` formatted as a bare UUID with no type prefix, plus a `created_at` timestamp in ISO 8601 UTC with three fractional digits. Most resources additionally carry `updated_at` (same format, refreshed on any mutation) and `version` (an integer starting at 1 that increments by one on every mutation). Two resource kinds are deliberately leaner: `GoldCardEvaluation` and `ComplianceEvent` carry only `id` and `created_at` — both `updated_at` and `version` are absent from them, because an evaluation is an immutable point-in-time snapshot and a compliance event is an append-only audit record.

Every mutation of a resource — whether driven by a client call or by an internal cascade such as a guideline publish bumping its owning criteria set — refreshes `updated_at` and increments `version` on the mutated resource. Cascades settle immediately, inside the triggering request; there is no eventual consistency window.

### 2.5. The Logical Clock and Turnaround Compliance

The platform does not trust wall-clock time. A server-managed logical clock timestamps intake (`received_at`), determination issuance (`issued_at`), and appeal filing. At startup the clock reads exactly `2026-08-01T00:00:00Z`, and the server must not fall back to wall-clock time before an administrator explicitly sets the clock. An admin-only test-driving capability advances the logical clock to a supplied `to_iso8601` instant — adopted unconditionally, with no monotonicity guard, so an instant earlier than the current reading is accepted — and immediately runs the turnaround-breach sweep described below; the response reports the new `current_utc` along with `requests_flagged` and `appeals_flagged`, the counts of rows newly flagged by that sweep (already-flagged rows are skipped and not counted).

Turnaround deadlines derive from the criteria set's regulation dimension. A request's `due_at` is its `received_at` plus the SLA hours for the pairing of the request's `urgency` and the governing criteria set's `line_of_business`: 24 hours for `URGENT` requests under `MEDICARE` or `MEDICAID`, 48 hours for `URGENT` requests under `COMMERCIAL`, 72 hours for `STANDARD` requests under `MEDICARE`, 120 hours for `STANDARD` requests under `MEDICAID`, and 168 hours for `STANDARD` requests under `COMMERCIAL`. An appeal's `due_at` is its `received_at` plus 720 hours (the 30-day appeal SLA).

Breach comparison is strict and measured in whole seconds: a case breaches only when the logical clock is strictly later than its `due_at`; at the exact `due_at` instant the case is still compliant. The clock-advance sweep flags every undetermined request (one in `PENDED_REVIEW` or `ESCALATED_MD`) and every undecided appeal (one in `RECEIVED` or `IN_REVIEW`) whose `due_at` is strictly before the new clock, setting the sticky boolean `is_tat_breached` and emitting a `TAT_BREACHED` compliance event per flagged row. Every `TAT_BREACHED` event is both request-scoped and provider-scoped: a flagged request's event carries that request's id and provider id, while a flagged appeal's event carries the appeal's underlying request id and that request's provider id, so an appeal breach surfaces in the request-scoped and provider-scoped event listings as well as in the system-wide query. The sweep is idempotent — rows already flagged are skipped and produce no duplicate events. Independently of the sweep, a determination issued with `issued_at` strictly later than the request's `due_at` marks the request breached at issuance and emits the same event, with the same idempotency: a request already flagged emits no second event at issuance.

### 2.6. Optimistic Concurrency Control on Guideline Transitions

Exactly one endpoint in the API participates in optimistic concurrency control: the guideline-version transition operation. A request to publish or retire a guideline version must carry `expected_criteria_set_version`, a non-optional input holding the client's last observed `version` of the owning criteria set. If the value does not match the criteria set's current `version`, the request is rejected with `ERR_STALE_VERSION` (HTTP 412). This captures the case where another policy editor has just published or retired a version — legitimately superseding or changing the published set under the library rules — leaving the current writer's view of the criteria set stale. The OCC check runs before any business validation on that endpoint. Endpoints not named here do not take a version field.

### 2.7. Validation Order

When several checks could reject the same call, they are evaluated in a fixed priority order so the surfaced error is deterministic. First, presence of the identity headers (§2.1). Second, role permission for the endpoint. Third, left-to-right existence of path identifiers — each id in the URL is resolved in order and the first missing resource yields `ERR_NOT_FOUND` (HTTP 404). Fourth, request-body well-formedness under `ERR_INVALID_REQUEST` (HTTP 400): required fields present and correctly typed, enum values inside their domains, body-supplied foreign keys (`provider_id`, `criteria_set_id`, `determination_id`, `supersedes_version_id`) referencing existing resources, `member_ref` non-empty, `scheduled_end` strictly after `scheduled_start`, `reason_code` consistent with the decision mapping (an `APPROVE` decision pairs with `MEDICAL_NECESSITY_MET`; a `DENY` decision pairs with one of the three denial codes; `reason_code` must be omitted on `ESCALATE` and `SEND_BACK`), and no duplicate `npi` across providers. Fifth — and only on the guideline-transition endpoint — the OCC check of §2.6. Sixth, target-state preconditions (the state-machine guards of §3, e.g. `ERR_REQUEST_NOT_PENDING`). Seventh, segregation-of-duties and due-process rules. Eighth, cross-reference consistency rules. Ninth, the guideline-retire in-flight guard. Tenth, temporal interval conflicts. Eleventh and last, the gold-card eligibility thresholds. A request that fails an earlier category never surfaces a later category's error.

### 2.8. Segregation of Duties and Due Process

Four due-process rules cut across the review pipeline; violations of the first three return HTTP 403, the fourth returns HTTP 409. A `MedicalDirector` may not decide an escalated case that they themselves escalated while acting as the reviewer: on any medical-director decision the caller's `X-User-ID` must differ from the request's `escalated_by_user_id`, else `ERR_SEGREGATION_OF_DUTIES`. An `AppealsReviewer` may not begin review of an appeal whose underlying determination they issued: when the determination's `decided_by_user_id` is non-null, a begin-review caller equal to it is rejected with `ERR_SEGREGATION_OF_DUTIES` (a system-issued auto-approval has a null decider and imposes no such bar). An appeal decision must come from the assigned reviewer — the caller must equal the appeal's `reviewer_id`, else `ERR_NOT_ASSIGNED_REVIEWER`. A peer-to-peer conference must be resolved by the medical director who scheduled it — the caller must equal the conference's `md_user_id`, else `ERR_NOT_ASSIGNED_MD`. Finally, a medical-director denial is blocked while any conference for the same request remains `SCHEDULED`, surfacing `ERR_P2P_CONFERENCE_OUTSTANDING` (HTTP 409).

### 2.9. Compliance Event Audit Trail

Every material compliance occurrence appends a `ComplianceEvent` row. The `event_type` is one of `AUTO_APPROVAL_FIRED`, `TAT_BREACHED`, `GOLD_CARD_GRANTED`, `GOLD_CARD_SUSPENDED`, `DELEGATION_SUSPENDED`, `DETERMINATION_VOIDED`, or `APPEAL_OVERTURNED`. Each event carries a human-readable `details` string and, depending on scope, a `request_id`, a `provider_id`, or neither — an event that is neither request-scoped nor provider-scoped (the delegation-suspension event is the example) carries null for both and is reachable only through the system-wide event query. Events scoped to a provider can be listed under the provider, events scoped to a request under the request, and the unscoped query across the whole audit log accepts optional `event_type`, `request_id`, and `provider_id` filters (the provider-scoped and request-scoped listings also accept `event_type`).

### 2.10. Rates, Precision, and Rounding

All approval and overturn rates in the system are computed to 4 decimal places using round-half-up. A rate whose denominator count is zero is represented as null rather than zero. Turnaround arithmetic uses whole seconds with the strict comparison of §2.5. Notice text is an exact-string contract — segment order and separators are part of it (§3.4).

## 3. Business Logic & Workflows

### 3.1. The Criteria Library: Sets, Versions, and Supersession

The clinical criteria library is the reference backbone of every determination. A `ClinicalPolicyEditor` authors a `ClinicalCriteriaSet` by supplying a `name` (the library name that will later appear in determination notices), a `line_of_business` drawn from `COMMERCIAL`, `MEDICARE`, or `MEDICAID` — the regulation dimension that drives turnaround SLAs — and a `service_category` naming the service category the set governs, which the gold-card program matches against. A new set starts in `DRAFT` status.

Within a set, the editor creates `GuidelineVersion` records, each carrying a human `version_label` (such as `1.0`, also rendered into notices), the clinical criteria text as `content`, an `auto_approve_eligible` flag declaring whether requests pinned to this version may auto-approve through the rules lane, an inclusive `effective_from` timestamp opening the effective window, an optional inclusive `effective_until` closing it (null means open-ended), and an optional `supersedes_version_id` naming the published version in the same set that this version will replace on publish. A new version starts `DRAFT`.

Publishing a version (moving it from `DRAFT` to `PUBLISHED`) is the library's most guarded operation. The OCC guard of §2.6 runs first. The owning criteria set must be in `DRAFT` or `ACTIVE` — publishing under a `RETIRED` set is rejected with `ERR_INVALID_GUIDELINE_TRANSITION`, as is any publish attempted on a version not currently `DRAFT`. If `supersedes_version_id` is present it must belong to the same criteria set (`ERR_SUPERSEDES_CROSS_SET`, HTTP 422) and must currently be `PUBLISHED` (`ERR_INVALID_GUIDELINE_TRANSITION` otherwise). The new version's closed effective window — from `effective_from` through `effective_until`, with a null `effective_until` extending indefinitely — must not intersect the closed window of any other `PUBLISHED` version in the same set; the version being superseded is excluded from this overlap check. An intersecting publish is rejected with `ERR_GUIDELINE_WINDOW_OVERLAP`. On a successful publish the version becomes `PUBLISHED`; if it named a superseded version, that version moves to `SUPERSEDED` and its `effective_until` is clamped to one second before the new version's `effective_from`; and the owning criteria set's `version` increments by one. The `PUBLISHED → SUPERSEDED` move happens only as this side effect — never via a direct transition call.

A version may also be retired. A `DRAFT` version retires freely (subject to the OCC guard). A `PUBLISHED` version retires only when no request pinned to it sits in `PENDED_REVIEW` or `ESCALATED_MD`; otherwise the retire is rejected with `ERR_GUIDELINE_HAS_INFLIGHT_REQUESTS`. Any retire attempted on a version not in the appropriate from-state is `ERR_INVALID_GUIDELINE_TRANSITION`. Either retire increments the owning set's `version` by one. The transition body's `to_status` is validated against the full guideline-status domain — `DRAFT`, `PUBLISHED`, `SUPERSEDED`, `RETIRED`; naming `DRAFT` or `SUPERSEDED` as the target passes body validation and is then rejected with `ERR_INVALID_GUIDELINE_TRANSITION`, since `SUPERSEDED` is reachable only as a publish side effect.

The set itself activates from `DRAFT` to `ACTIVE` only when at least one of its guideline versions is `PUBLISHED`; activation with zero published versions is rejected with `ERR_NO_ACTIVE_GUIDELINE`, and activation from any state other than `DRAFT` is `ERR_INVALID_CRITERIA_SET_TRANSITION`. An `ACTIVE` set retires to `RETIRED` — a transition that increments the set's `version` and deliberately leaves in-flight requests untouched, because requests pin their guideline version at intake and never re-pin. `DRAFT → RETIRED` and any transition out of `RETIRED` are invalid, and naming `DRAFT` as the `to_status` target is likewise rejected with `ERR_INVALID_CRITERIA_SET_TRANSITION`. Both set transitions are performed by the `ClinicalPolicyEditor` and take `to_status` in the request body. Guideline versions can also be listed with optional `criteria_set_id`, `supersedes_version_id`, and `status` filters, which gives clients reverse reachability from a version back to its set or its supersession target.

### 3.2. Request Intake: Pinning, Auto-Adjudication, and Delegation Gating

An `IntakeSpecialist` opens a case by supplying `provider_id` (the requesting provider), `member_ref` (an external member identifier string — there is no member registry behind it), `criteria_set_id`, the requested `service_code`, an `urgency` of `STANDARD` or `URGENT`, an `intake_channel` of `PORTAL`, `FAX`, `PHONE`, or `EDI`, and a `documentation_complete` boolean declaring whether the required clinical documentation was attached at intake.

Intake runs three gates in narrative order. First, the criteria set must be `ACTIVE`; a set in any other status rejects intake with `ERR_CRITERIA_SET_NOT_ACTIVE`. Second, delegation: if the criteria set's delegation arrangement is `SUSPENDED`, intake is rejected with `ERR_DELEGATION_SUSPENDED` (§3.7). Third, guideline pinning: the server selects the `PUBLISHED` version of the set whose closed effective window contains the intake timestamp — `effective_from` on or before `received_at`, and `effective_until` either null or on or after `received_at` — ranking candidates by `effective_from` descending with ties broken by creation order, the most recently created version winning (equivalent to `created_at` descending whenever the clock has not moved backwards between creations). If no published window contains the timestamp, intake fails with `ERR_NO_ACTIVE_GUIDELINE`. The chosen version is stored as the request's `guideline_version_id` and is **never re-pinned**: later supersession or retirement of the version does not disturb the request.

With pinning complete, `received_at` is stamped from the logical clock, `due_at` is computed per §2.5, and the auto-approval decision runs synchronously inside the intake call. Two lanes exist. The **gold lane** fires when the provider's `gold_card_status` is `GOLD_CARDED` and the provider's `gold_card_service_category` equals the criteria set's `service_category`. The **rules lane** fires when the pinned guideline version's `auto_approve_eligible` is true, the `intake_channel` is `PORTAL` or `EDI`, and `documentation_complete` is true. The gold lane is evaluated first, so a request satisfying both lanes records `reason_code` `GOLD_CARD_AUTO`. When the gold lane fires, the request becomes `AUTO_APPROVED` and a determination is created with `outcome` `APPROVED`, `reason_code` `GOLD_CARD_AUTO`, `decided_by_role` `SYSTEM_RULE`, `decided_by_user_id` null, `guideline_version_id` copied from the pinned version, `status` `FINAL`, and `issued_at` from the clock; the request's `determined_at` is set to that same instant, and an `AUTO_APPROVAL_FIRED` compliance event is recorded with the request and provider ids. When only the rules lane fires the same shape results with `reason_code` `AUTO_RULE`. When neither lane fires, the request lands in `PENDED_REVIEW` and awaits human review. The transient `RECEIVED` state exists only inside the intake call and is never observable afterwards.

Requests can be listed with `provider_id`, `criteria_set_id`, `guideline_version_id`, `status`, and `urgency` filters alongside the standard `limit` and `offset` parameters. While a request is in `PENDED_REVIEW` or `ESCALATED_MD`, the `IntakeSpecialist` may withdraw it — moving it to the terminal `WITHDRAWN` state and, as a conditional cascade, moving any peer-to-peer conference still `SCHEDULED` for the request to `CANCELLED`. Withdrawal from any other status is rejected with `ERR_REQUEST_NOT_WITHDRAWABLE`.

### 3.3. The Two-Tier Review Ladder and Peer-to-Peer Conferences

A `ClinicalReviewer` works the `PENDED_REVIEW` queue by posting a `decision`. Three outcomes exist, each with its own `reason_code` contract enforced under `ERR_INVALID_REQUEST` (HTTP 400): an `APPROVE` decision requires `reason_code` `MEDICAL_NECESSITY_MET`; a `DENY` decision requires one of `MEDICAL_NECESSITY_NOT_MET`, `INSUFFICIENT_INFO`, or `EXPERIMENTAL_INVESTIGATIONAL`; an `ESCALATE` decision requires `reason_code` to be omitted. Any reviewer decision on a request not in `PENDED_REVIEW` is rejected with `ERR_REQUEST_NOT_PENDING`.

Approval moves the request `PENDED_REVIEW → APPROVED` and creates a `FINAL` determination with `decided_by_role` `CLINICAL_REVIEWER`, `decided_by_user_id` taken from `X-User-ID`, `outcome` `APPROVED`, and `issued_at` from the clock; `determined_at` is set, and if `issued_at` is strictly later than `due_at` the request's `is_tat_breached` flips true and a `TAT_BREACHED` event is emitted. The provider's rolling and lifetime statistics then recompute and the gold-card auto-suspend check runs (§3.6). Denial moves the request `PENDED_REVIEW → DENIED` with the same determination shape (outcome `DENIED`) and the same downstream recompute; this reviewer denial is the trigger that can flip a provider from `GOLD_CARDED` to `SUSPENDED` and emit `GOLD_CARD_SUSPENDED`. Escalation instead moves the request to `ESCALATED_MD`, recording `escalated_by_user_id` from `X-User-ID`, and creates no determination.

A `MedicalDirector` works the escalated queue. Every medical-director decision first requires the request to be `ESCALATED_MD` (`ERR_REQUEST_NOT_ESCALATED`) and the caller to differ from `escalated_by_user_id` (`ERR_SEGREGATION_OF_DUTIES`). `APPROVE` requires `reason_code` `MEDICAL_NECESSITY_MET` and moves the request `ESCALATED_MD → APPROVED` with a `MEDICAL_DIRECTOR` determination, `determined_at`, late-determination breach marking, and the provider-stats recompute plus auto-suspend check. `DENY` requires one of the three denial reason codes and is additionally blocked while any peer-to-peer conference for the request is `SCHEDULED` — that block surfaces `ERR_P2P_CONFERENCE_OUTSTANDING`; when the caller also escalated the case, the segregation check runs first and surfaces `ERR_SEGREGATION_OF_DUTIES`. `SEND_BACK` takes no `reason_code` and returns the request to `PENDED_REVIEW` with `escalated_by_user_id` cleared to null — the send-back cycle that lets the reviewer tier take another pass.

Peer-to-peer conferences belong to the escalated phase. A `MedicalDirector` schedules one for a request by supplying `scheduled_start` and `scheduled_end`; the interval is half-open, and `scheduled_end` must be strictly after `scheduled_start` (`ERR_INVALID_REQUEST` otherwise). Scheduling requires the request to be `ESCALATED_MD` (`ERR_REQUEST_NOT_ESCALATED`). The scheduling director is recorded as `md_user_id` and the conference starts `SCHEDULED`. Two conflict rules guard the calendar under `ERR_P2P_SCHEDULE_CONFLICT` (HTTP 409): the new half-open interval must not intersect any other `SCHEDULED` conference of the same medical director — intervals that merely touch at an endpoint do not conflict — and a request may have at most one `SCHEDULED` conference at a time. The scheduling medical director later resolves the conference by supplying an `outcome` of `COMPLETED` or `NO_SHOW`; resolution requires the conference to be `SCHEDULED` (`ERR_P2P_NOT_RESOLVABLE`) and the caller to equal `md_user_id` (`ERR_NOT_ASSIGNED_MD`). Either resolution unblocks the medical-director denial path for the request. Conferences also cancel automatically when their parent request is withdrawn, and a request's conferences can be listed under the request.

### 3.4. Determinations, Notice Content, and Voids

Every determination — auto or human — shares one shape: the `request_id` it belongs to, an `outcome` of `APPROVED` or `DENIED`, a `reason_code` from `GOLD_CARD_AUTO`, `AUTO_RULE`, `MEDICAL_NECESSITY_MET`, `MEDICAL_NECESSITY_NOT_MET`, `INSUFFICIENT_INFO`, or `EXPERIMENTAL_INVESTIGATIONAL`, the deciding tier as `decided_by_role` (`SYSTEM_RULE`, `CLINICAL_REVIEWER`, or `MEDICAL_DIRECTOR`), the decider's `decided_by_user_id` (null for system decisions), the `guideline_version_id` copied from the request's pinned version, `issued_at`, and a `status` that starts `FINAL` and can later become `OVERTURNED` (via appeal) or `VOID` (via admin). A request carries at most one non-`VOID` determination, and its `determined_at` mirrors the current non-void determination's `issued_at`.

The `notice_text` is rendered at issuance from an exact-string template. Segments are joined by pipe characters in this fixed order: the literal `OUTCOME:` followed by the outcome; `|SERVICE:` followed by the request's `service_code`; `|REASON:` followed by the reason code; `|CRITERIA:` followed by the criteria set's `name`, an at-sign, and the pinned version's `version_label`; `|ISSUED:` followed by `issued_at` in ISO 8601 UTC with three fractional digits; `|APPEAL_BY:` followed by the appeal deadline — `issued_at` plus 4,320 hours (the 180-day appeal window) — in the same format; and `|DECIDED_BY:` followed by the deciding role. Segment order and separators are contractual. `notice_text` is persisted on the determination at issuance; determinations can be read individually or listed with `request_id` and `guideline_version_id` filters, and both the individual read and the list rows include `notice_text`.

A `UMAdmin` may void a determination, but only one in `FINAL` status with no appeal against it sitting in `RECEIVED` or `IN_REVIEW`; otherwise `ERR_DETERMINATION_NOT_VOIDABLE`. Voiding sets the determination `VOID` and reverts the request: a determination decided by `SYSTEM_RULE` or `CLINICAL_REVIEWER` sends the request back to `PENDED_REVIEW` (from `AUTO_APPROVED` or `APPROVED` for the reviewer case, and from `DENIED` for a reviewer denial), while a `MEDICAL_DIRECTOR` determination sends it back to `ESCALATED_MD` (from `APPROVED` or `DENIED`), with `escalated_by_user_id` retaining its prior value in the medical-director cases. In every void, `determined_at` is cleared to null, provider statistics recompute excluding the voided row (void rows never count toward any rate), and a `DETERMINATION_VOIDED` event is recorded with the request and provider ids.

### 3.5. Appeals: Filing, Review, and the Overturn Cascade

An `AppealsClerk` files an appeal against a determination by supplying a free-text `appeal_reason`. Filing requires the determination to be `FINAL`; filing against a determination in any other status is rejected with `ERR_INVALID_APPEAL_STATE`. At most one appeal per determination may exist in a non-withdrawn status — a second filing while an earlier appeal sits in `RECEIVED`, `IN_REVIEW`, `UPHELD`, or `OVERTURNED` is rejected with `ERR_APPEAL_ALREADY_OPEN`. A filed appeal starts `RECEIVED`, stamps `received_at` from the clock, and computes its `due_at` as `received_at` plus 720 hours. Its `is_tat_breached` flag follows the sweep rules of §2.5, and its `decided_at` stays null until a decision.

Review begins when an `AppealsReviewer` begins review on a `RECEIVED` appeal; any other from-state is `ERR_INVALID_APPEAL_STATE`. The segregation rule of §2.8 bars the reviewer who issued the appealed determination. Beginning review moves the appeal to `IN_REVIEW` and records the caller as `reviewer_id`. The assigned reviewer — and only the assigned reviewer (`ERR_NOT_ASSIGNED_REVIEWER`) — then decides the appeal by supplying an `outcome` of `UPHELD` or `OVERTURNED` with an optional `rationale` (accepted but not persisted on the appeal); deciding from any state other than `IN_REVIEW` is `ERR_INVALID_APPEAL_STATE`. Either decision stamps `decided_at` from the clock. An `AppealsClerk` may instead withdraw an undecided appeal from `RECEIVED` or `IN_REVIEW` to the terminal `WITHDRAWN` state; withdrawing an appeal in any other status is rejected with `ERR_INVALID_APPEAL_STATE`.

An `UPHELD` decision ends the matter. An `OVERTURNED` decision fires a cross-entity cascade: the determination moves `FINAL → OVERTURNED` (keeping its recorded `outcome` of `DENIED` — the overturn is expressed through status, not by rewriting the outcome), the request moves `DENIED → APPROVED`, provider statistics recompute with the overturned denial now counting as an approval, and an `APPEAL_OVERTURNED` compliance event is recorded with the request and provider ids. Appeals are readable individually and listed under their determination.

### 3.6. Provider Statistics and the Gold-Carding Program

Provider oversight rests on a single inclusion set: determinations joined through their requests' `provider_id` whose status is `FINAL` or `OVERTURNED` and whose `decided_by_role` is `CLINICAL_REVIEWER` or `MEDICAL_DIRECTOR`. System-rule auto-approvals and voided determinations never count. Within that set, a determination counts as an effective approval when it is `FINAL` with `outcome` `APPROVED`, or when it is `OVERTURNED` regardless of the recorded outcome. Two variants derive from the same set: the **rolling** variant restricts to determinations whose `issued_at` falls within the trailing 90 days of the logical clock — both bounds inclusive, 2,160 hours — and the **lifetime** variant applies no window. Each variant yields a count, an approval count, and a rate (approvals divided by count, 4 decimal places round-half-up, null when the count is zero). These live on the provider as `rolling_determination_count`, `rolling_approval_count`, `rolling_approval_rate`, `lifetime_determination_count`, `lifetime_approval_count`, and `lifetime_approval_rate`, recomputed on determination issuance, determination void, the appeal-overturn cascade, and gold-card evaluation.

Providers enter the registry through a `UMAdmin` supplying a unique `npi` (a duplicate `npi` is rejected under `ERR_INVALID_REQUEST`), a `name`, and an optional `specialty`. New providers start `NOT_GOLD_CARDED` with all counters at zero and `gold_card_service_category` null.

A `UMAdmin` grants the gold card by running an evaluation for a supplied `service_category`. Evaluation is blocked outright for a provider already `GOLD_CARDED` (`ERR_ALREADY_GOLD_CARDED`). Otherwise the rolling statistics are recomputed first — counting only human-lane determinations, which breaks the circular dependency in which gold-card auto-approvals would otherwise inflate the very rate used to keep the gold card — and eligibility requires a `rolling_determination_count` of at least 10 and a `rolling_approval_rate` of at least 0.90, both thresholds inclusive (exactly 0.9000 is eligible; a zero count yields a null rate and is never eligible). An ineligible evaluation is rejected with `ERR_GOLD_CARD_NOT_ELIGIBLE` (HTTP 422) and creates no record. A successful evaluation writes a `GoldCardEvaluation` capturing the `window_start` (evaluation time minus 90 days, an inclusive lower bound), `window_end` (the evaluation instant), the observed `window_determination_count`, the observed `window_approval_rate` at 4 decimal places, and a `decision` of `REINSTATED` when the provider was `SUSPENDED` or `GRANTED` otherwise. The provider becomes `GOLD_CARDED` with `gold_card_service_category` set to the evaluated category, and a `GOLD_CARD_GRANTED` event is recorded. Evaluations are listable under the provider.

Suspension is automatic, not administrative. Whenever provider statistics recompute after a human-lane determination insert or a determination void, the auto-suspend check runs: if the provider is `GOLD_CARDED` and the recomputed rolling count is at least 10 while the rolling rate is strictly below 0.90, the provider flips to `SUSPENDED`, `gold_card_service_category` clears to null, and a `GOLD_CARD_SUSPENDED` event is recorded. Reinstatement is simply another evaluation that passes eligibility on the freshly recomputed rolling stats.

### 3.7. Delegation Oversight and Audit Findings

The vendor operates under delegation arrangements with health plans. A `UMAdmin` creates a `DelegationArrangement` from a `delegating_plan_name` and a `criteria_set_id` scoping the delegated authority; at most one arrangement may exist per criteria set (`ERR_ARRANGEMENT_ALREADY_EXISTS`). A new arrangement is `ACTIVE` with `open_deficiency_count` zero. Arrangements are listable with a `criteria_set_id` filter.

A `ComplianceOfficer` audits by recording an `AuditFinding` under an arrangement — the finding's `arrangement_id` is the arrangement named in the URL path — supplying the `determination_id` of the audited determination and a `finding_type` of `COMPLIANT`, `NOTICE_DEFICIENT`, `CRITERIA_MISAPPLIED`, or `TAT_VIOLATION`. The audited determination must fall inside the arrangement's scope — its request's `criteria_set_id` must equal the arrangement's `criteria_set_id` — else `ERR_DELEGATION_SCOPE_MISMATCH` (HTTP 422). Finding creation is blocked while the arrangement is `SUSPENDED` (`ERR_DELEGATION_SUSPENDED`). A new finding starts `OPEN`.

The deficiency threshold drives the arrangement automatically. The `open_deficiency_count` is the number of the arrangement's findings that are `OPEN` with a `finding_type` other than `COMPLIANT`. When a newly created finding lifts that count to 3 — the comparison is inclusive, so the third open deficiency suspends — the arrangement flips `ACTIVE → SUSPENDED`, a `DELEGATION_SUSPENDED` event is recorded with null request and provider ids (its `details` reference the arrangement), and subsequent intake for the criteria set is rejected per §3.2. When the `ComplianceOfficer` closes a finding by transitioning it from `OPEN` to `CLOSED` (any close attempted on a non-`OPEN` finding is `ERR_FINDING_NOT_OPEN`, as is naming `OPEN` as the `to_status` target), the count recomputes; if it has dropped below 3 and the arrangement is `SUSPENDED`, the arrangement cascades back to `ACTIVE` and intake for the criteria set unblocks. Findings are listable both under their arrangement and under the determination they reference.

### 3.8. Overturn Analysis Metrics

Program-level oversight reads from a dedicated metrics endpoint returning seven aggregates over all appeal rows: `appeals_filed` (every appeal ever created, any status, including withdrawn and in-flight), `appeals_decided` (appeals in `UPHELD` or `OVERTURNED`), `appeals_withdrawn`, `overturned_count`, `upheld_count`, and two rate variants at 4 decimal places round-half-up. `overturn_rate_decided` divides `overturned_count` by the sum of `upheld_count` and `overturned_count` — the regulatory overturn analysis, whose denominator excludes withdrawn and undecided appeals. `overturn_rate_filed` divides `overturned_count` by `appeals_filed` — the program-intake burden view, which for identical data is strictly smaller whenever undecided or withdrawn appeals exist. Either rate is null when its denominator is zero.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource return `200 OK`. All paths are mounted under the `/um` prefix shown below, and each path matches with or without a trailing slash.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/um/providers` | Register a provider organization | UMAdmin |
| GET | `/um/providers/{id}` | Get a provider including recomputed-as-of-last-event stats | Any role |
| POST | `/um/providers/{id}/gold-card-evaluations` | Run a gold-card eligibility evaluation for a service category; grants or reinstates the gold card on success | UMAdmin |
| GET | `/um/providers/{id}/gold-card-evaluations` | List gold-card evaluations for a provider | Any role |
| GET | `/um/providers/{id}/compliance-events` | List compliance events scoped to a provider | Any role |
| POST | `/um/criteria-sets` | Create a clinical criteria set | ClinicalPolicyEditor |
| GET | `/um/criteria-sets/{id}` | Get a criteria set (carries the OCC version used by guideline transitions) | Any role |
| POST | `/um/criteria-sets/{id}/transition` | Transition criteria set DRAFT to ACTIVE (requires at least one PUBLISHED guideline version) or ACTIVE to RETIRED | ClinicalPolicyEditor |
| POST | `/um/criteria-sets/{id}/guideline-versions` | Create a DRAFT guideline version in the set | ClinicalPolicyEditor |
| GET | `/um/guideline-versions/{id}` | Get a guideline version | Any role |
| GET | `/um/guideline-versions` | List/filter guideline versions (by criteria set, supersession target, or status) | Any role |
| POST | `/um/guideline-versions/{id}/transition` | Publish (DRAFT to PUBLISHED, with supersede/window semantics) or retire (DRAFT/PUBLISHED to RETIRED) a guideline version; OCC-guarded on the owning criteria set | ClinicalPolicyEditor |
| POST | `/um/prior-auth-requests` | Intake a prior-auth request; pins the governing guideline version and runs auto-adjudication synchronously | IntakeSpecialist |
| GET | `/um/prior-auth-requests/{id}` | Get a request | Any role |
| GET | `/um/prior-auth-requests` | List/filter requests (by provider, criteria set, guideline version, status, or urgency; supports pagination) | Any role |
| POST | `/um/prior-auth-requests/{id}/withdraw` | Withdraw a pending/escalated request; cancels any SCHEDULED peer-to-peer conference | IntakeSpecialist |
| POST | `/um/prior-auth-requests/{id}/reviewer-decision` | Clinical reviewer tier decision: APPROVE / DENY (creates a determination) or ESCALATE to the medical director | ClinicalReviewer |
| POST | `/um/prior-auth-requests/{id}/md-decision` | Medical director tier decision: APPROVE / DENY (creates a determination) or SEND_BACK to the reviewer tier | MedicalDirector |
| POST | `/um/prior-auth-requests/{id}/peer-to-peer-conferences` | Schedule a peer-to-peer conference for an escalated request (half-open interval per medical director) | MedicalDirector |
| GET | `/um/prior-auth-requests/{id}/peer-to-peer-conferences` | List peer-to-peer conferences for a request | Any role |
| POST | `/um/peer-to-peer-conferences/{id}/resolve` | Resolve a scheduled conference as COMPLETED or NO_SHOW by its scheduling medical director | MedicalDirector |
| GET | `/um/determinations/{id}` | Get a determination (includes notice_text) | Any role |
| GET | `/um/determinations` | List/filter determinations (by request or guideline version) | Any role |
| POST | `/um/determinations/{id}/void` | Void a FINAL determination with no open appeal; reverts the request and provider stats | UMAdmin |
| POST | `/um/determinations/{id}/appeals` | File an appeal against a FINAL determination | AppealsClerk |
| GET | `/um/determinations/{id}/appeals` | List appeals for a determination | Any role |
| GET | `/um/determinations/{id}/audit-findings` | List audit findings referencing a determination | Any role |
| GET | `/um/appeals/{id}` | Get an appeal | Any role |
| POST | `/um/appeals/{id}/begin-review` | Begin review; assigns the calling appeals reviewer; segregation vs original decider enforced | AppealsReviewer |
| POST | `/um/appeals/{id}/decide` | Decide an appeal UPHELD or OVERTURNED (overturn cascades to determination, request, provider stats, and the audit log) | AppealsReviewer |
| POST | `/um/appeals/{id}/withdraw` | Withdraw an undecided appeal | AppealsClerk |
| POST | `/um/delegation-arrangements` | Create a delegation arrangement for a criteria set (at most one per set) | UMAdmin |
| GET | `/um/delegation-arrangements/{id}` | Get a delegation arrangement | Any role |
| GET | `/um/delegation-arrangements` | List/filter delegation arrangements (by criteria set) | Any role |
| POST | `/um/delegation-arrangements/{id}/audit-findings` | Record an audit finding against a determination in the arrangement's scope | ComplianceOfficer |
| GET | `/um/delegation-arrangements/{id}/audit-findings` | List audit findings for an arrangement | Any role |
| POST | `/um/audit-findings/{id}/transition` | Close an OPEN finding; the count dropping below 3 resumes a SUSPENDED arrangement | ComplianceOfficer |
| GET | `/um/prior-auth-requests/{id}/compliance-events` | List compliance events scoped to a request | Any role |
| GET | `/um/compliance-events` | Query the audit log across all scopes (the only read path for events carrying neither request nor provider scope) | Any role |
| GET | `/um/metrics/overturn-analysis` | Overturn analysis aggregates across all appeals (both rate variants) | Any role |
| POST | `/um/_clock/set_current_utc` | Set the logical clock, then run the turnaround-breach sweep | UMAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_CRITERIA_SET_NOT_ACTIVE` | 409 Conflict |
| `ERR_INVALID_CRITERIA_SET_TRANSITION` | 409 Conflict |
| `ERR_NO_ACTIVE_GUIDELINE` | 409 Conflict |
| `ERR_INVALID_GUIDELINE_TRANSITION` | 409 Conflict |
| `ERR_SUPERSEDES_CROSS_SET` | 422 Unprocessable Entity |
| `ERR_GUIDELINE_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_GUIDELINE_HAS_INFLIGHT_REQUESTS` | 409 Conflict |
| `ERR_REQUEST_NOT_PENDING` | 409 Conflict |
| `ERR_REQUEST_NOT_ESCALATED` | 409 Conflict |
| `ERR_REQUEST_NOT_WITHDRAWABLE` | 409 Conflict |
| `ERR_P2P_CONFERENCE_OUTSTANDING` | 409 Conflict |
| `ERR_P2P_SCHEDULE_CONFLICT` | 409 Conflict |
| `ERR_P2P_NOT_RESOLVABLE` | 409 Conflict |
| `ERR_NOT_ASSIGNED_MD` | 403 Forbidden |
| `ERR_DELEGATION_SUSPENDED` | 409 Conflict |
| `ERR_ARRANGEMENT_ALREADY_EXISTS` | 409 Conflict |
| `ERR_DELEGATION_SCOPE_MISMATCH` | 422 Unprocessable Entity |
| `ERR_FINDING_NOT_OPEN` | 409 Conflict |
| `ERR_GOLD_CARD_NOT_ELIGIBLE` | 422 Unprocessable Entity |
| `ERR_ALREADY_GOLD_CARDED` | 409 Conflict |
| `ERR_DETERMINATION_NOT_VOIDABLE` | 409 Conflict |
| `ERR_INVALID_APPEAL_STATE` | 409 Conflict |
| `ERR_APPEAL_ALREADY_OPEN` | 409 Conflict |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_NOT_ASSIGNED_REVIEWER` | 403 Forbidden |
