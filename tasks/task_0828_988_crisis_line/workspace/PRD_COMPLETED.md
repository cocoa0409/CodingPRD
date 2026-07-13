# Crisis Line Dispatch API — Product Requirements Document

## 1. Introduction

The Crisis Line Dispatch API is the operational backbone of a 988 crisis line and its mobile-crisis dispatch network. It carries a caller from the moment of first contact — across phone, chat, or text — through structured risk screening, de-escalation and safety planning, warm hand-off to mobile crisis teams, crisis-receiving-center bed placement, 911 coordination, and post-crisis follow-up. Every one of these steps is time-sensitive and clinically consequential, so the system treats each contact as a stateful case whose disposition is driven by a defensible risk score rather than by ad-hoc judgement alone.

Three staff populations share the platform. Front-line clinical counselors run intake, screening, de-escalation, and wellness follow-up; logistics dispatchers coordinate mobile teams, bed referrals, center availability, and emergency escalation; and clinical supervisors oversee everything the other two roles do while additionally configuring teams and centers, closing out resolved cases, and pulling operational reports. Because a single mishandled escalation can be a matter of life and death, the API enforces strict ordering of its safety checks, keeps immediate consistency between callers and the scarce resources (team slots and crisis beds) allocated to them, and guards shared resources against stale writes.

This document specifies the complete contract: the request/response envelope, the role model, the lifecycle of every entity, the scoring and aggregation calculations, and the full validation and error taxonomy. A conforming implementation must reproduce these rules exactly, because downstream clinical decisions and the automated conformance suite both depend on them.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelopes, and cross-cutting principles that apply uniformly across every endpoint.

### 2.1. User and Role-Based Access Control

Every request must be authenticated through two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the operational capacity under which they act. The system recognizes exactly three roles, spelled precisely as `CrisisCounselor`, `CrisisDispatcher`, and `ClinicalSupervisor`. If either header is missing, or if `X-User-Role` carries a value that is not one of these three known roles, the request is rejected with `ERR_UNAUTHENTICATED`. When the headers are well-formed but the acting role is not permitted to perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED`.

The three roles form a hierarchical override model. A `CrisisCounselor` handles the clinical stream: risk screening, safety-plan authoring and transitions, wellness-check outreach attempts, plus shared intake and the clinical disposition branches. A `CrisisDispatcher` handles the logistics stream: mobile dispatch, bed referral, crisis-center status changes, and 911 escalation, plus shared intake and the dispatch/emergency disposition branches. A `ClinicalSupervisor` is a strict superset of both: any operation either of the other two roles may perform, a `ClinicalSupervisor` may also perform, and in addition it exclusively owns team creation, center creation, closing a resolved contact, and the operations report.

All three roles use an opaque identity model. When `X-User-Role` is `CrisisCounselor`, `CrisisDispatcher`, or `ClinicalSupervisor`, `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity; the server may record it (for example, capturing the acting role as `initiated_by_role` on an `EmergencyCoordination` record when a transition writes it) but never compares it to any entity's `id` for ownership. There are no per-record ownership checks in this system: authorization is purely role-based, determined by the operation being invoked and the role asserted in `X-User-Role`.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, and it accepts values from a minimum of 1 to a maximum of 100. The `offset` parameter is the number of items to skip from the front of the result set and defaults to 0. Out-of-range and malformed values are silently coerced rather than rejected: a `limit` below 1 is raised to 1 and a `limit` above 100 is capped at 100, while a missing or non-integer `limit` falls back to 10; a negative or non-integer `offset` falls back to 0. Pagination parameters never produce an error.

Unless a specific endpoint states otherwise, every list endpoint returns its resources sorted by their creation timestamp (`created_at`) in ascending order; ties on `created_at` are broken by ascending creation order (the order in which the rows were inserted). Each list response carries the pagination bookkeeping in the `meta` object of the envelope, namely `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. The Logical Clock and Temporal Semantics

The system runs on a logical clock rather than wall-clock time. On startup the clock reads exactly `2026-03-01T00:00:00Z`, and until an operator explicitly moves it, every time-dependent computation reads that fixed instant — the server never falls back to real-world time. An operator may advance or set the clock by supplying a `to_iso8601` instant to the clock-setting capability; from that point the clock holds the supplied value until it is set again.

The logical clock is the sole source of "now" for four things: the `disposition_at` stamped on a contact when it leaves screening, the wait component of dispatch priority scoring, the `scheduled_at` due time of follow-up outreach, and every dated-window comparison used in temporal-overlap checks. Because all of these read the same clock, tests can pin the clock, create resources, advance it, and observe deterministic results.

All datetime windows in the system are treated as half-open intervals: `window_start` is inclusive and `window_end` is exclusive, so two windows that merely touch (one's end equal to the other's start) are considered non-overlapping. Any dated window supplied on a create must satisfy that its end is strictly after its start; a window whose `window_end` is less than or equal to its `window_start` (and, for a team, a shift whose `shift_end` is less than or equal to its `shift_start`) is rejected at body validation with `ERR_WINDOW_INVALID`.

### 2.5. Common Resource Properties

Every primary resource carries a server-minted `id` formatted as a UUID with no type prefix. Resources also carry a `created_at` timestamp, an ISO 8601 UTC value with three fractional digits, recorded from the logical clock at creation.

Most resources additionally carry an `updated_at` timestamp (same ISO 8601 UTC format) and an integer `version` that begins at 1 and increments by one on every mutation of the resource. The `Contact`, `RiskScreening`, `SafetyPlan`, `MobileCrisisTeam`, `MobileDispatch`, `CrisisCenter`, `BedReferral`, `FollowUpTask`, and `RepeatCaller` resources all carry the full set: `id`, `created_at`, `updated_at`, and `version`. Whenever any field of one of these resources changes — including derived fields such as a contact's `risk_band` or a center's `available_beds` — the server refreshes `updated_at` and increments `version`.

The `EmergencyCoordination` record is the sole exception. It is an append-only 911 hand-off record that is never modified after creation, so it carries only `id` and `created_at`; it has no `updated_at` and no `version` field at all.

### 2.6. Numeric Precision and Rounding

Both scoring calculations — the risk-screening score and the dispatch priority score — are performed entirely in integer arithmetic with no rounding; wherever a division appears (for example, converting elapsed milliseconds to whole minutes, or stepping a wait time), the fractional part is discarded by taking the floor. The bed and slot ledgers are pure integer counts.

The operations report is the only place fractional rounding occurs, and it uses the round-half-up convention. Two report figures round to one decimal place — the average time to disposition and the follow-up compliance rate — following the exact evaluation order given in §3.9. No other value in the system is rounded.

### 2.7. Optimistic Concurrency Control

Two create operations reserve capacity on a shared parent resource, and both are guarded by optimistic concurrency control against that parent's `version`. OCC here is a stale-version check, not a timing or race construct: the request simply declares the parent version the client last observed, and the server refuses the write if its own copy has moved on.

Creating a bed referral must carry `expected_crisis_center_version`, which the client sets to the `version` of the target `CrisisCenter` it last read. If that value does not equal the center's current `version` — meaning another writer has since created or voided a hold on that center and thereby advanced its version, leaving the current writer's view of bed availability stale — the create is rejected with `ERR_STALE_VERSION` at HTTP 412. Likewise, creating a mobile dispatch must carry `expected_team_version`, set to the `version` of the target `MobileCrisisTeam` the client last read; if it does not equal the team's current `version` — because another writer has reserved or released a slot on that team and advanced its version, leaving the current writer's view of remaining capacity stale — the create is rejected with `ERR_STALE_VERSION` at HTTP 412. No other endpoint accepts or requires a version field, and endpoints outside these two creates perform no OCC check.

### 2.8. Request Validation Order

When more than one thing is wrong with a request, the system reports failures in a fixed precedence so that the returned `error_id` is deterministic. The order is: (1) authentication of the headers, yielding `ERR_UNAUTHENTICATED`; (2) role authorization for the operation, yielding `ERR_UNAUTHORIZED`; (3) existence of every referenced resource — each path id and each foreign key in the body, checked left to right, yielding the matching not-found error (`ERR_CONTACT_NOT_FOUND`, `ERR_SCREENING_NOT_FOUND`, `ERR_SAFETY_PLAN_NOT_FOUND`, `ERR_TEAM_NOT_FOUND`, `ERR_DISPATCH_NOT_FOUND`, `ERR_CENTER_NOT_FOUND`, `ERR_REFERRAL_NOT_FOUND`, `ERR_FOLLOWUP_NOT_FOUND`, or `ERR_EMERGENCY_NOT_FOUND`); (4) body-field validity — required fields present and well-formed (`ERR_VALIDATION`), enum fields carrying an allowed value (`ERR_INVALID_ENUM`), and dated windows satisfying end-after-start (`ERR_WINDOW_INVALID`); (5) the target resource being in a legal from-state for the requested transition, yielding `ERR_INVALID_STATE`; (6) the optimistic-concurrency check, yielding `ERR_STALE_VERSION`; (7) the safety branch — disposition matching the risk band and the active-safety-plan precondition, yielding `ERR_DISPOSITION_NOT_ALLOWED` or `ERR_NO_ACTIVE_SAFETY_PLAN`; (8) cross-entity referential preconditions, yielding `ERR_CONTACT_NOT_DISPATCH_PENDING`, `ERR_CENTER_OFFLINE`, or `ERR_ACUITY_NOT_ACCEPTED`; (9) temporal-overlap checks, yielding `ERR_TEAM_WINDOW_CONFLICT` or `ERR_BED_WINDOW_CONFLICT`; and (10) team availability, yielding `ERR_TEAM_OFF_SHIFT` or `ERR_TEAM_AT_CAPACITY`. Earlier checks strictly precede later ones: for example, a request that both targets a non-existent contact and carries an invalid enum surfaces the not-found error, because existence (3) precedes body validity (4). The existence pass itself walks path ids first and body foreign keys next, in left-to-right textual order, and returns the not-found error for the first identifier that fails to resolve.

### 2.9. Bed and Slot Ledgers

Two scarce resources are tracked by conserved integer ledgers that are always recomputed from the underlying rows, never drifted by ad-hoc increments.

For a crisis center, `held_beds` is the count of that center's bed referrals currently in `HELD`, and `occupied_beds` is the count currently in `ADMITTED`. The center's `available_beds` is its `bed_capacity` minus `held_beds` minus `occupied_beds`. The invariant `available_beds + held_beds + occupied_beds == bed_capacity` holds at every moment.

For a mobile crisis team, `active_dispatch_count` is the count of that team's dispatches currently in `REQUESTED`, `EN_ROUTE`, or `ON_SCENE`. The team's remaining capacity is its `capacity` minus `active_dispatch_count`, and the invariant that remaining capacity plus `active_dispatch_count` equals `capacity` holds at every moment. Whenever a dispatch enters or leaves the active set, the owning team's `active_dispatch_count` is recomputed and its `version` is incremented.

## 3. Business Logic & Workflows

### 3.1. Intake and the Repeat-Caller Registry

A crisis case begins when a counselor, a dispatcher, or a supervisor records an intake. The intake captures the `channel` the caller reached the line on — one of `PHONE`, `CHAT`, or `TEXT` — and a `caller_key`, a stable hashed identifier that lets the platform recognize the same caller across separate contacts without storing raw personal data. Intake may optionally record a `caller_phone`, a `caller_name`, and a free-text `presenting_concern`. A newly created contact enters the lifecycle in `INTAKE` status. It has no `risk_score`, `risk_band`, `latest_screening_id`, `disposition`, or `disposition_at` yet; `has_active_safety_plan` starts false, `emergency_status` starts `NONE`.

The `caller_key` links a contact to the **repeat-caller registry**, a per-caller record keyed uniquely by `caller_key`. The connection is by equality of `caller_key`, not a foreign-key id. On every intake the registry entry for that `caller_key` is upserted: if no entry exists one is created (its `registry_status` is always `ACTIVE`), and its `contact_count` — the number of contacts sharing this `caller_key` — is recomputed to include the new contact. The registry's `high_risk_flag` is then recomputed: it is true when the `contact_count` is at least 3, or when the caller's `last_risk_band` is `IMMINENT`; otherwise it is false. At the moment of intake the contact takes a snapshot of the registry's freshly recomputed `high_risk_flag` into its own `repeat_caller_flag`; this snapshot is frozen on the contact and does not move if the registry later changes. The registry's `last_risk_band` — the risk band of the most recently screened contact for this `caller_key` — is only established once screenings exist (see §3.2); until then it is null.

Determining "most recent" for `last_risk_band` uses the contact with the greatest `created_at` among those sharing the `caller_key`; if two share the same `created_at`, the tie is broken by the greatest `disposition_at`. Should any further tie remain, the lexically greatest `id` may be used purely as an inert display ordering — it must never change the value of `high_risk_flag` or any other decision. The registry can be listed and filtered by `caller_key` or by `high_risk_flag`; the `high_risk_flag` filter matches true only for the literal value `true` (case-insensitive) and treats any other supplied value as false.

### 3.2. Risk Screening and Banding

A counselor (or a supervisor) submits a **risk screening** against a contact, identified by `contact_id`. Each screening declares a `screening_type` of either `PROVISIONAL` (a rapid intake triage taken before protective factors are weighed) or `COMPREHENSIVE` (a full assessment). It records `suicidal_ideation` and `plan_specificity`, each an integer severity from 0 to 3; `means_access`, a boolean for whether the caller can reach lethal means; `prior_attempts`, a non-negative count of previous attempts; and an optional `protective_factors` count that defaults to 0. Each screening stores its own computed `risk_score` and `risk_band`.

The screening `risk_score` is built from four weighted components minus a protective term. The ideation component is the `suicidal_ideation` value, capped at 3, multiplied by 3. The plan component is the `plan_specificity` value, capped at 3, multiplied by 4. If `means_access` is true, a flat 5 points are added; if false, this component contributes nothing. The prior-attempts component is `prior_attempts` capped at 3, multiplied by 2. From the sum of those four components the system subtracts the protective term, and the resulting `risk_score` is that difference but never below zero — any negative result is floored to 0. All arithmetic is integer.

The protective term is where the two screening variants diverge on identical inputs. For a `PROVISIONAL` screening the protective term is zero — protective factors are ignored during rapid triage, which yields the higher score. For a `COMPREHENSIVE` screening the protective term is the `protective_factors` count, capped at 3, multiplied by 2, which lowers the score and can pull the contact into a lower band. The band is then assigned by testing thresholds from the top down: the `risk_band` is `IMMINENT` when the score is at least 20; otherwise `HIGH` when the score is at least 12; otherwise `MODERATE` when the score is at least 6; otherwise `LOW`.

Submitting a screening has consequences beyond the screening row. The system copies the new screening's `risk_score` and `risk_band` onto the contact, and sets the contact's `latest_screening_id` to the new screening's id. The contact's `latest_screening_id` always points at the screening with the greatest `created_at` for that contact (a later screening supersedes an earlier one; a tie on `created_at` may resolve to the greatest id only as an inert display convenience, never as a decision input). The **first** screening for a contact also advances that contact from `INTAKE` to `SCREENED`, which is legal only while the contact is in `INTAKE`. In all cases, the screening updates the caller's registry entry: the registry's `last_risk_band` is set to this screening's band and the `high_risk_flag` is recomputed under the same rule as intake (at-least-3 contacts or an `IMMINENT` last band). Screenings can be listed and filtered by `contact_id` or `screening_type`.

### 3.3. Disposition: Choosing the Care Pathway

Once a contact is `SCREENED`, it must be routed onto exactly one care pathway, and the pathway a caller is eligible for is gated by the risk band that screening produced. Disposition is driven by supplying a `to_status` that names the target state.

A counselor may route a `SCREENED` contact toward de-escalation, moving it to `DE_ESCALATION`; this is permitted only when the contact's `risk_band` is `LOW` or `MODERATE`, and any other band is rejected with `ERR_DISPOSITION_NOT_ALLOWED`. This transition sets the contact's `disposition` to `DE_ESCALATION` and stamps `disposition_at` with the current logical-clock time. A dispatcher may route a `SCREENED` contact toward mobile dispatch, moving it to `DISPATCH_PENDING`; this is permitted only when the `risk_band` is exactly `HIGH`, and any other band is rejected with `ERR_DISPOSITION_NOT_ALLOWED`. It sets `disposition` to `MOBILE_DISPATCH` and stamps `disposition_at`. A dispatcher may also route a `SCREENED` contact straight to emergency, moving it to `EMERGENCY_911`; this is permitted only when the `risk_band` is exactly `IMMINENT`, and any other band is rejected with `ERR_DISPOSITION_NOT_ALLOWED`. The emergency route sets `disposition` to `EMERGENCY`, stamps `disposition_at`, sets `emergency_status` to `INITIATED`, and creates the 911 hand-off record described in §3.7. Each disposition is available only from `SCREENED`; attempting it from any other state fails the from-state check with `ERR_INVALID_STATE`.

### 3.4. Safety Planning

Parallel to disposition, a counselor authors a **safety plan** for a contact identified by `contact_id`. A safety plan records `coping_strategies` and `warning_signs` (each a list), an optional list of `support_contacts`, and a `lethal_means_counseling` boolean that defaults to false to record whether means-restriction counseling was delivered. A new safety plan is created in `DRAFT`.

A counselor activates a plan by moving it from `DRAFT` to `ACTIVE`, which is legal only from `DRAFT`. Activation enforces a single-active-plan rule per contact: if any other safety plan for the same contact is currently `ACTIVE`, that prior plan is archived to `ARCHIVED` as a side effect, and the contact's `has_active_safety_plan` is set to true. A counselor may also archive a plan by moving it from `ACTIVE` to `ARCHIVED` (legal only from `ACTIVE`); when a plan is archived this way, the system checks whether any `ACTIVE` plan remains for the contact, and if none does, it sets the contact's `has_active_safety_plan` back to false. A `DRAFT` plan may instead be archived directly from `DRAFT` to `ARCHIVED`, which carries no side effect on the contact. `ARCHIVED` is terminal.

The active-safety-plan state matters because a de-escalation case cannot be closed out without one. A counselor resolves a `DE_ESCALATION` contact by moving it to `RESOLVED`, but this is permitted only when the contact's `has_active_safety_plan` is true; if the contact has no active safety plan the resolution is rejected with `ERR_NO_ACTIVE_SAFETY_PLAN`. A successful resolution schedules a follow-up task, as described in §3.8.

### 3.5. Mobile Crisis Dispatch

A supervisor configures a **mobile crisis team** with a `name`, a `coverage_zone` code, a `capacity` (the maximum concurrent active dispatches, defaulting to 1 and never below 1), a shift window bounded by `shift_start` (inclusive) and `shift_end` (exclusive), and an availability `status` of either `ON_SHIFT` (the default) or `OFF_SHIFT`. A freshly created team starts with `active_dispatch_count` at 0 and `version` at 1.

When a contact sits in `DISPATCH_PENDING`, a dispatcher requests a mobile dispatch, naming the `contact_id`, the `team_id`, the requested on-scene window via `window_start` and `window_end`, a `requested_acuity` of `LOW`, `MODERATE`, `HIGH`, or `IMMINENT`, and the OCC guard `expected_team_version`. The dispatch is created in `REQUESTED`; the owning team's `active_dispatch_count` is incremented and its `version` is incremented; and the dispatch's `priority_score_estimated` is pinned at creation. Dispatch creation is subject to a cascade of preconditions beyond the OCC check: the contact must be in `DISPATCH_PENDING`, else `ERR_CONTACT_NOT_DISPATCH_PENDING`; the requested window must not collide with the team's other windows (see below), else `ERR_TEAM_WINDOW_CONFLICT`; and the team must be available (see below), else `ERR_TEAM_OFF_SHIFT` or `ERR_TEAM_AT_CAPACITY`.

Team availability requires the team to be `ON_SHIFT` with the requested window falling entirely inside the team's shift window; a team that is `OFF_SHIFT`, or a request whose window is not contained within `[shift_start, shift_end)`, is rejected with `ERR_TEAM_OFF_SHIFT`. Separately, the team must have a free concurrent slot — that is, its `active_dispatch_count` must be below its `capacity`; a team already carrying `capacity` active dispatches is rejected with `ERR_TEAM_AT_CAPACITY`. The team window-conflict rule is single-capacity and buffer-separated: a 15-minute turnaround must sit between any two of a team's dispatches. Concretely, the new dispatch conflicts with any other dispatch for the same team whose status is `REQUESTED`, `EN_ROUTE`, `ON_SCENE`, or `COMPLETED` when the new window's start is earlier than that other window's end plus 15 minutes and, at the same time, that other window's start is earlier than the new window's end plus 15 minutes; such a collision is rejected with `ERR_TEAM_WINDOW_CONFLICT`.

The dispatch **priority score** measures urgency as the sum of three parts: a band weight, a wait penalty, and a repeat bonus. The band weight is 100 for a band of `IMMINENT`, 60 for `HIGH`, 30 for `MODERATE`, and 10 for `LOW`. The wait penalty reflects how long the caller has waited: take the elapsed time from the contact's `created_at` to the applicable clock reading expressed as whole minutes (discarding any fractional minute), divide that by 10 taking only the whole-number quotient (discarding the remainder), cap that quotient at 5, and multiply by 4. The repeat bonus is a flat 15 points when the repeat-caller registry entry for the contact's `caller_key` has its `high_risk_flag` set, and 0 otherwise. The two stored variants differ only in their band and their clock reading. The `ESTIMATED` variant, pinned into `priority_score_estimated` at dispatch creation, uses the contact's `risk_band` (its disposition-time band) as the band and measures the wait at the creation-time clock. The `REASSESSED` variant, computed when the team arrives on scene and stored into `priority_score_reassessed`, uses the `on_scene_acuity` reported on arrival as the band and measures the wait at the later on-scene clock reading; before the on-scene arrival, `priority_score_reassessed` is null.

A dispatcher advances a dispatch through its lifecycle by supplying a `to_status`. From `REQUESTED` the dispatch advances to `EN_ROUTE` (no side effects). From `EN_ROUTE` it advances to `ON_SCENE`, which requires an `on_scene_acuity` value on the request; that value is stored as the dispatch's `on_scene_acuity`, and the `REASSESSED` priority is recomputed at that moment into `priority_score_reassessed`. From `ON_SCENE` the dispatch reaches `COMPLETED`; completion decrements the team's `active_dispatch_count` and increments the team's `version`, and if the linked contact is still in `DISPATCH_PENDING` it drives that contact from `DISPATCH_PENDING` to `RESOLVED`, which schedules a follow-up task. A dispatch may be cancelled to `CANCELLED` from any of `REQUESTED`, `EN_ROUTE`, or `ON_SCENE`; every cancellation decrements the team's `active_dispatch_count` and increments the team's `version`, and voids any bed referral still `HELD` that was linked to this dispatch (which continues the cascade into the center's `held_beds`, per §3.6). Each transition is legal only from its named from-state; any other origin is rejected with `ERR_INVALID_STATE`. `COMPLETED` and `CANCELLED` are terminal.

### 3.6. Crisis-Center Bed Referral

A supervisor configures a **crisis receiving center** with a `name`, a `bed_capacity` (at least 1), and an `accepted_acuities` list naming which of `LOW`, `MODERATE`, `HIGH`, and `IMMINENT` the center will take. A new center opens with `status` `ONLINE`, `held_beds` at 0, `occupied_beds` at 0, and `version` at 1; its `available_beds` follows the ledger in §2.9.

When a contact is in `DISPATCH_PENDING`, a dispatcher holds a bed by creating a **bed referral**, naming the `contact_id`, the `crisis_center_id`, an optional `mobile_dispatch_id` (set when the referral originates from an on-scene team), the `acuity` being referred, the hold window via `window_start` and `window_end`, and the OCC guard `expected_crisis_center_version`. A successful referral is created in `HELD`; the center's `held_beds` is incremented and its `version` is incremented; and the contact is driven from `DISPATCH_PENDING` to `REFERRAL_PENDING`. Beyond OCC, referral creation checks that the contact is in `DISPATCH_PENDING` (else `ERR_CONTACT_NOT_DISPATCH_PENDING`), that the center is `ONLINE` (else `ERR_CENTER_OFFLINE`), that the center's `accepted_acuities` includes the referral's `acuity` (else `ERR_ACUITY_NOT_ACCEPTED`), and that the hold window does not exhaust the center's bed capacity. This center window rule is aggregate-capacity and half-open with no buffer: the referral is rejected with `ERR_BED_WINDOW_CONFLICT` if adding the new hold would bring the count of the center's referrals in `HELD` or `ADMITTED` whose `[window_start, window_end)` interval overlaps the new interval to at least `bed_capacity`. Because the intervals are half-open, two holds that merely touch end-to-start do not overlap.

The `DISPATCH_PENDING` and `REFERRAL_PENDING` states form a revision cycle that lets a case bounce between "needs a bed" and "bed held" as circumstances change. A dispatcher advances a referral by supplying a `to_status`. Admitting a referral moves it from `HELD` to `ADMITTED`, which is legal only from `HELD` and only while the center is `ONLINE` (an admit against a `DIVERTED` center is rejected with `ERR_CENTER_OFFLINE`); admission decrements the center's `held_beds` and increments its `occupied_beds`, and if the linked contact is in `REFERRAL_PENDING` it drives that contact from `REFERRAL_PENDING` to `RESOLVED`, scheduling a follow-up task. Discharging a referral moves it from `ADMITTED` to `DISCHARGED` and decrements the center's `occupied_beds`. Voiding a referral moves it from `HELD` to `VOIDED`; voiding decrements the center's `held_beds`, and if the linked contact is in `REFERRAL_PENDING` — and that contact is not being escalated to `EMERGENCY_911` in the very same request — it reverts the contact from `REFERRAL_PENDING` back to `DISPATCH_PENDING`. A referral may reach `VOIDED` either through an explicit void by a dispatcher or through a system cascade from a dispatch cancellation or a center diversion. `DISCHARGED` and `VOIDED` are terminal; any transition attempted from an illegal from-state is rejected with `ERR_INVALID_STATE`.

A dispatcher controls center availability by supplying a `to_status`. Diverting a center moves it from `ONLINE` to `DIVERTED`: as a cascade, every one of that center's referrals still in `HELD` is transitioned `HELD` to `VOIDED`, and each such void decrements `held_beds` and reverts its contact from `REFERRAL_PENDING` to `DISPATCH_PENDING`; the center's `version` is then incremented. Bringing a center back moves it from `DIVERTED` to `ONLINE` and increments the center's `version`. Referrals can be listed and filtered by `contact_id`, `crisis_center_id`, `mobile_dispatch_id`, or `status`.

### 3.7. 911 Emergency Coordination

An escalation to `EMERGENCY_911` can be initiated from several points in a contact's life, and each escalation records an append-only **emergency coordination** hand-off. Whenever a contact enters `EMERGENCY_911`, the system sets the contact's `emergency_status` to `INITIATED` and creates an `EmergencyCoordination` record carrying the `contact_id`, a `psap_reference` token for the 911 (PSAP) hand-off, a `risk_band_at_escalation` snapshot of the contact's `risk_band` at that instant, and the `initiated_by_role` naming the role that triggered the hand-off.

Beyond the direct `SCREENED`-to-`EMERGENCY_911` route in §3.3, a dispatcher may escalate a contact that is in `DISPATCH_PENDING` or in `REFERRAL_PENDING`, and a counselor may escalate a contact that is in `DE_ESCALATION`. Escalating from `DISPATCH_PENDING` or `REFERRAL_PENDING` first cancels the contact's active mobile dispatch (any dispatch in `REQUESTED`, `EN_ROUTE`, or `ON_SCENE`) to `CANCELLED`, if one exists; from `REFERRAL_PENDING` this begins the escalate cascade, since cancelling the dispatch voids the linked `HELD` bed referral, whose `VOIDED` transition decrements the center's `held_beds` — and note that because this contact is being escalated in the same request, the void does not revert the contact back to `DISPATCH_PENDING`. Escalating from `DE_ESCALATION` has no dispatch to cancel and simply performs the emergency side effects. In every case the escalation sets `emergency_status` to `INITIATED` and creates the coordination record. A contact in `EMERGENCY_911` is resolved by a dispatcher moving it to `RESOLVED`, which schedules a follow-up task. Coordination records can be retrieved individually or listed and filtered by `contact_id`.

### 3.8. Follow-Up and Wellness Checks

Every path that resolves a contact — de-escalation resolution, mobile-dispatch completion, bed admission, and post-emergency resolution — schedules a **follow-up task** as a side effect. A follow-up task is created in `SCHEDULED` with `attempt_count` at 0, its `channel` mirrored from the contact's `channel`, its `contact_id` carried from the contact, and its `scheduled_at` due time set to the current logical-clock time plus a fixed follow-up delay of 1440 minutes (that is, 24 hours from resolution). Each task also carries a `max_attempts` ceiling that defaults to 3 and governs when outreach is abandoned.

A counselor records each outreach attempt by supplying an `outcome` — either `REACHED` or `NO_ANSWER` — and, optionally, a `next_scheduled_at` instant. Recording an attempt is legal only when the task is in `SCHEDULED` or `RESCHEDULED`; it increments `attempt_count` by 1 and stores the given `outcome`. The attempt then resolves in the same request: if the `outcome` is `REACHED`, the task completes to `COMPLETED`; if the `outcome` is `NO_ANSWER` and the incremented `attempt_count` has reached or exceeded `max_attempts`, the task is abandoned to `ABANDONED`; otherwise the task moves to `RESCHEDULED` and its `scheduled_at` is reset to the supplied `next_scheduled_at`. The `RESCHEDULED`-attempt-`RESCHEDULED` loop is the wellness-check retry cycle, and it terminates either when the caller is reached or when the attempt ceiling is hit. `COMPLETED` and `ABANDONED` are terminal; the transient `ATTEMPTED` state is never observed at rest because it resolves within the same request. Follow-up tasks can be listed and filtered by `contact_id` or `status`.

Once a contact reaches `RESOLVED`, the case is administratively closed by a supervisor driving it from `RESOLVED` to `CLOSED`; this close is reserved exclusively to the `ClinicalSupervisor` role, is legal only while the contact is in `RESOLVED`, and carries no further side effects. `CLOSED` is the terminal state of the contact lifecycle.

### 3.9. Operations Reporting

A supervisor pulls an **operations report** over an optional window bounded by `window_start` and `window_end`. The report returns `total_contacts`, a `contacts_by_disposition` breakdown, an `avg_time_to_disposition_minutes` figure, a `followup_compliance_rate_pct`, and a `bed_utilization_by_center` breakdown. Both `total_contacts` and `contacts_by_disposition` are computed over the same population used for the average below — the contacts whose `disposition_at` is non-null and falls within the report window (all contacts with a non-null `disposition_at` when the window is omitted): `total_contacts` is the size of that population, and `contacts_by_disposition` is a map from each `disposition` value to the count of population contacts bearing it, with the three keys `DE_ESCALATION`, `MOBILE_DISPATCH`, and `EMERGENCY` always present and defaulting to 0.

The average-time-to-disposition figure is computed over the population of contacts that have a non-null `disposition_at` falling within the report window, treated as a half-open interval with `window_start` inclusive and `window_end` exclusive; if the window parameters are omitted, the population is all contacts that have a non-null `disposition_at`. The evaluation order is pinned and must not be shortened. First, for each contact in the population, compute the elapsed time from its `created_at` to its `disposition_at` in minutes and round that per-contact figure to a whole number of minutes using round-half-up — this per-contact rounding happens before any summing. Then, if the population is empty, the average is 0.0. Otherwise, sum the already-rounded per-contact minutes, divide by the number of contacts in the population, and round that mean to one decimal place using round-half-up. Summing raw values and rounding once at the end is explicitly not the intended computation. The `followup_compliance_rate_pct` is the count of all follow-up tasks currently in `COMPLETED` divided by the count of all follow-up tasks that exist, expressed as a percentage and rounded to one decimal place with round-half-up; this figure is computed over every follow-up task regardless of the report window, and when no follow-up tasks exist it is 0.0. The bed-utilization breakdown, `bed_utilization_by_center`, is a map keyed by each center's `id` whose entry for a center carries that center's `bed_capacity`, `held_beds`, `occupied_beds`, and `available_beds` from the same held/occupied/available ledger described in §2.9.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource return a `201 Created` status code. Operations that read a resource, list a collection, drive a state transition, record an attempt, set the clock, or return a report return a `200 OK` status code. Request and response payloads are not repeated here — they are specified by the narratives in §3 and the global rules in §2.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/contacts` | Create a crisis Contact (intake); upserts the repeat-caller registry | CrisisCounselor, CrisisDispatcher, ClinicalSupervisor |
| GET | `/contacts/{contactId}` | Get one Contact | CrisisCounselor, CrisisDispatcher, ClinicalSupervisor |
| GET | `/contacts` | List Contacts | CrisisCounselor, CrisisDispatcher, ClinicalSupervisor |
| POST | `/contacts/{contactId}/state` | Drive Contact disposition, escalation, resolution, or close | CrisisCounselor, CrisisDispatcher, ClinicalSupervisor |
| POST | `/risk-screenings` | Submit a risk screening for a Contact | CrisisCounselor, ClinicalSupervisor |
| GET | `/risk-screenings/{screeningId}` | Get one RiskScreening | CrisisCounselor, CrisisDispatcher, ClinicalSupervisor |
| GET | `/risk-screenings` | List RiskScreenings | CrisisCounselor, CrisisDispatcher, ClinicalSupervisor |
| POST | `/safety-plans` | Create a SafetyPlan (DRAFT) for a Contact | CrisisCounselor, ClinicalSupervisor |
| GET | `/safety-plans/{safetyPlanId}` | Get one SafetyPlan | CrisisCounselor, CrisisDispatcher, ClinicalSupervisor |
| GET | `/safety-plans` | List SafetyPlans | CrisisCounselor, CrisisDispatcher, ClinicalSupervisor |
| POST | `/safety-plans/{safetyPlanId}/state` | Activate or archive a SafetyPlan | CrisisCounselor, ClinicalSupervisor |
| POST | `/mobile-crisis-teams` | Create a MobileCrisisTeam | ClinicalSupervisor |
| GET | `/mobile-crisis-teams/{teamId}` | Get one MobileCrisisTeam | CrisisCounselor, CrisisDispatcher, ClinicalSupervisor |
| POST | `/mobile-dispatches` | Dispatch a team to a DISPATCH_PENDING contact | CrisisDispatcher, ClinicalSupervisor |
| GET | `/mobile-dispatches/{dispatchId}` | Get one MobileDispatch | CrisisCounselor, CrisisDispatcher, ClinicalSupervisor |
| GET | `/mobile-dispatches` | List MobileDispatches | CrisisCounselor, CrisisDispatcher, ClinicalSupervisor |
| POST | `/mobile-dispatches/{dispatchId}/state` | Advance or cancel a MobileDispatch | CrisisDispatcher, ClinicalSupervisor |
| POST | `/crisis-centers` | Create a CrisisCenter | ClinicalSupervisor |
| GET | `/crisis-centers/{centerId}` | Get one CrisisCenter | CrisisCounselor, CrisisDispatcher, ClinicalSupervisor |
| POST | `/crisis-centers/{centerId}/state` | Set a CrisisCenter ONLINE or DIVERTED | CrisisDispatcher, ClinicalSupervisor |
| POST | `/bed-referrals` | Hold a crisis bed for a DISPATCH_PENDING contact | CrisisDispatcher, ClinicalSupervisor |
| GET | `/bed-referrals/{referralId}` | Get one BedReferral | CrisisCounselor, CrisisDispatcher, ClinicalSupervisor |
| GET | `/bed-referrals` | List BedReferrals | CrisisCounselor, CrisisDispatcher, ClinicalSupervisor |
| POST | `/bed-referrals/{referralId}/state` | Admit, discharge, or void a BedReferral | CrisisDispatcher, ClinicalSupervisor |
| GET | `/follow-up-tasks/{taskId}` | Get one FollowUpTask | CrisisCounselor, CrisisDispatcher, ClinicalSupervisor |
| GET | `/follow-up-tasks` | List FollowUpTasks | CrisisCounselor, CrisisDispatcher, ClinicalSupervisor |
| POST | `/follow-up-tasks/{taskId}/attempt` | Record a wellness-check outreach attempt | CrisisCounselor, ClinicalSupervisor |
| GET | `/emergency-coordinations/{coordId}` | Get one EmergencyCoordination record | CrisisCounselor, CrisisDispatcher, ClinicalSupervisor |
| GET | `/emergency-coordinations` | List EmergencyCoordination records | CrisisCounselor, CrisisDispatcher, ClinicalSupervisor |
| GET | `/repeat-callers` | List the repeat-caller registry | CrisisCounselor, CrisisDispatcher, ClinicalSupervisor |
| POST | `/_clock/set_current_utc` | Set the server logical clock | CrisisCounselor, CrisisDispatcher, ClinicalSupervisor |
| GET | `/reports/operations` | Operations report | ClinicalSupervisor |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_CONTACT_NOT_FOUND` | 404 |
| `ERR_SCREENING_NOT_FOUND` | 404 |
| `ERR_SAFETY_PLAN_NOT_FOUND` | 404 |
| `ERR_TEAM_NOT_FOUND` | 404 |
| `ERR_DISPATCH_NOT_FOUND` | 404 |
| `ERR_CENTER_NOT_FOUND` | 404 |
| `ERR_REFERRAL_NOT_FOUND` | 404 |
| `ERR_FOLLOWUP_NOT_FOUND` | 404 |
| `ERR_EMERGENCY_NOT_FOUND` | 404 |
| `ERR_VALIDATION` | 422 |
| `ERR_INVALID_ENUM` | 422 |
| `ERR_WINDOW_INVALID` | 422 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_DISPOSITION_NOT_ALLOWED` | 409 |
| `ERR_NO_ACTIVE_SAFETY_PLAN` | 409 |
| `ERR_CONTACT_NOT_DISPATCH_PENDING` | 409 |
| `ERR_CENTER_OFFLINE` | 409 |
| `ERR_ACUITY_NOT_ACCEPTED` | 409 |
| `ERR_BED_WINDOW_CONFLICT` | 409 |
| `ERR_TEAM_WINDOW_CONFLICT` | 409 |
| `ERR_TEAM_OFF_SHIFT` | 409 |
| `ERR_TEAM_AT_CAPACITY` | 409 |
