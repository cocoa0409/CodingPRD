# Lab Results & Critical Value Notification API — Product Requirements Document

## 1. Introduction

Clinical laboratories operate at the intersection of regulatory exposure (CLIA documentation, retention of attestation receipts) and time-critical patient safety: a potassium reading at panic-tier on a neonate is meaningless if the ordering physician never sees it within minutes of release. The current generation of lab information systems tends to optimize the analytical phase — instrument scheduling, result entry — while leaving the *pre-analytic chain of custody* (collection, transit, accessioning) and the *post-analytic critical-value loop* (deliver, acknowledge, escalate) under-instrumented. Operators stitch the gaps together by phone, paper, and pager, and audit trails are reconstructed after the fact.

This document specifies a single API that fuses both halves. It tracks each lab order through specimen collection, instrument scheduling, result release, and (where the result is critical) into a closed-loop notification chain that escalates automatically when an acknowledgement is not captured before the per-channel deadline. Concurrent writers are reconciled with optimistic concurrency tokens against the relevant parent resource so that a result release cannot quietly overwrite a peer's release, and an amendment cannot quietly overwrite a peer's amendment. The system additionally exposes a small admin clock control so the deadline mechanics — the most behaviourally subtle part of the workflow — are deterministically testable.

The intended audiences are ordering providers, phlebotomists, lab technicians, lab directors (the CLIA-responsible officer), and an integration tier that drives SMS and phone (IVR) delivery. All five act through the same REST surface, distinguished by the role header described in §2.1.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request MUST carry two headers: `X-User-ID` and `X-User-Role`. Missing, malformed, or unrecognised headers are rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose `X-User-Role` is syntactically valid but is not authorized for the called endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

`X-User-Role` MUST be one of exactly five values: `Anonymous`, `OrderingProvider`, `Phlebotomist`, `LabTech`, `LabDirector`. The system has no other roles.

The semantics of `X-User-ID` depend on which role is supplied:

- When `X-User-Role` is `Anonymous`, `X-User-ID` is an opaque pre-authentication token not bound to any persisted entity. The server may record it for audit purposes but does not compare it to any entity's `id`. `Anonymous` exists solely to bootstrap the very first `LabDirector` registration; once that record exists, subsequent clinician registrations are normally made by an authenticated `LabDirector`, but the registration endpoint accepts both.
- When `X-User-Role` is `OrderingProvider`, `Phlebotomist`, `LabTech`, or `LabDirector`, `X-User-ID` is the `id` of the acting `Clinician` row. Ownership checks on any resource that names a clinician through a foreign-key field — for example `ordering_clinician_id` on `LabOrder`, `collector_clinician_id` on `Specimen`, `recipient_clinician_id` on `CriticalNotification`, `acknowledging_clinician_id` on `AcknowledgementReceipt` — compare that field to `X-User-ID`. Where a sub-role check is also required (for example, an order can only be placed by a `Clinician` whose `role_type` is `ORDERING_PROVIDER`), both the role header and the underlying clinician's `role_type` MUST agree.

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

Every list endpoint accepts two query parameters: `limit` and `offset`. The `limit` parameter defaults to 10, has a minimum of 1, and a maximum of 100. The `offset` parameter defaults to 0. List responses always return items sorted by `created_at` ascending. The `meta` block on list responses includes `limit`, `offset`, `total_count`, and `has_more` alongside the standard request metadata.

### 2.4. Common Resource Properties and Identity

Every persisted entity carries a server-minted `id`, which is a UUID with no domain-specific type prefix. Most entities additionally carry a `created_at` and `updated_at` timestamp (ISO 8601 UTC, three fractional digits) and an integer `version` field that begins at 1 on creation and is incremented by exactly 1 on every successful mutation. The lone exception is the `AcknowledgementReceipt`: because the receipt is immutable by design — once an acknowledgement is captured, CLIA forbids editing it — `AcknowledgementReceipt` rows expose only `id` and `created_at`; they carry no `updated_at` and no `version` field.

Numeric measurements on a `Result` (the `numeric_value`, `reference_low`, `reference_high`, `critical_low`, `critical_high`) are stored and returned to two decimal places. Threshold comparisons against those numbers are exact at that resolution: a reading equal to `critical_low` is classified as `CRITICAL_LOW`, and a reading equal to `critical_high` is classified as `CRITICAL_HIGH`. Turn-around-time figures derived from clock subtraction are returned as integer minutes, computed by truncating any fractional seconds toward zero (floor).

### 2.5. Nested Resource Retrieval and Path-Parameter Validation

Several endpoints are scoped under a parent resource — for example, listing the lab orders that belong to a single patient is scoped under the patient's id, registering a specimen is scoped under a lab order's id, and opening a retest request is scoped under a result's id. Path parameters are resolved from left to right; the first id that does not resolve to a live row terminates the request with `ERR_NOT_FOUND` (HTTP 404), and foreign-key fields in the request body are validated against the same rule once the path-level lookups succeed.

### 2.6. Optimistic Concurrency Control

Two write operations require the client to attest, in the request body, to the parent resource version it last observed.

A `Result` release MUST include `expected_lab_order_version`, carrying the client's last observed `version` of the parent `LabOrder`. If, by the time the server processes the release, the `LabOrder.version` has advanced — typically because another `LabTech` has just released a sibling result on the same order and thereby legitimately bumped the order's version through the cascade described in §3 — the release is rejected with `ERR_STALE_LAB_ORDER_VERSION` and HTTP 412. The release is not retried automatically; the client is expected to re-read the order, reconcile, and resubmit.

A `Result` amendment MUST include `expected_result_version`, carrying the client's last observed `version` of the `Result` being amended. If the result's `version` has advanced since the client read it — typically because another `LabTech` has already amended the same row and a fresh `RELEASED` descendant now exists — the amendment is rejected with `ERR_STALE_RESULT_VERSION` and HTTP 412.

No other endpoint requires a version field in the request body. Mutations to specimens, lab orders (cancel), instruments, instrument runs, critical notifications, acknowledgements, and retest requests do not take a `version` parameter and are not subject to OCC rejection.

### 2.7. Cascading State Mutations and Version Bumps

Every successful state transition refreshes the target entity's `updated_at` and increments its `version` by one. Several transitions additionally mutate sibling or ancestor entities; in every such cascade, each entity touched by the cascade has its own `version` incremented and its own `updated_at` refreshed. Three cascades in particular bear emphasis because they are the source of nearly all OCC contention in the system:

- Releasing a `Result` from `PROVISIONAL` to `RELEASED` on the *first* releasable result of an order causes the parent `LabOrder` to transition from `ACCESSIONED` to `RESULTED`. Both the result and the order are version-bumped. This is the cascade that ordinarily provokes `ERR_STALE_LAB_ORDER_VERSION` on a peer release that started from a stale read.
- Accessioning a `Specimen` from `IN_TRANSIT` to `ACCESSIONED` on the *first* accessioned specimen of an order causes the parent `LabOrder` to transition from `DRAFT` to `ACCESSIONED`. Both the specimen and the order are version-bumped.
- Rejecting a `Specimen` on a `LabOrder` whose `specimens_count` drops to zero as a result cascades the order from `ACCESSIONED` to `CANCELLED` (the system, not a clinician, acts as the cancelling actor in this case). If the order had any `CriticalNotification` rows on its `Result` rows in `PENDING` or `SENT`, those notifications are further cascaded to `VOIDED`. This is a three-hop cascade: specimen rejection → order cancellation → notification voiding. Each affected entity gets its own `version` bump and `updated_at` refresh.

### 2.8. Counter Conservation Invariants

Two computed counters are maintained against strict conservation invariants:

- `LabOrder.specimens_count` is the number of specimens of that order whose `status` is not `REJECTED`. `LabOrder.accessioned_count` is the number whose `status` is `ACCESSIONED`. Both are recomputed after every specimen-state transition, before any cascade reads them. The post-recompute values drive the downstream cascade described in §2.7 — in particular, the `ACCESSIONED → CANCELLED` order cascade only fires when the post-recompute `specimens_count` is exactly zero.
- `Patient.results_release_count` is the number of `Result` rows belonging to that patient whose `status` is `RELEASED`. Across the lifetime of a patient, the sum of all increments (`+1` per release) and decrements (`−1` per invalidation) MUST equal the count of currently-released rows for that patient. Amendment is a zero-net event because the old row leaves `RELEASED` (entering `AMENDED`) at the same time the new row enters `RELEASED`. `Patient.critical_incidents_count`, by contrast, is monotone non-decreasing: it is incremented when a `CriticalNotification` transitions into `SENT` for the first time and is never decremented thereafter, even on subsequent voiding.

### 2.9. CLIA Safety Posture and Compliance Flagging

Two sets of rules implement the laboratory's CLIA documentation posture. First, certain transitions are forbidden because they would orphan a clinically released finding: an `ACCESSIONED` `Specimen` that has a `RELEASED` `Result` against it cannot be rejected — the lab director must first invalidate the result. Second, certain cascade endpoints set `LabOrder.compliance_incident` to `true`; once set, it is never cleared. The canonical trigger is a `CriticalNotification` escalation: when a notification is escalated from `SENT` to `ESCALATED`, the parent order's `compliance_incident` flag is raised as a second-hop side effect, recording an enduring incident for the CLIA audit log.

### 2.10. Validation Priority Ordering

When multiple validation conditions apply to the same request, they are evaluated in a fixed order so that the most security-significant failure mode is always the one reported. Independent of this priority order, structural problems with the request itself — a required input field omitted, a type mismatch, or an enum value outside the declared set — are rejected with `ERR_INVALID_REQUEST` (HTTP 400). The order of the substantive checks is: authentication of the caller's headers, role-based authorization for the endpoint, existence of every path-id and foreign-key referent (left-to-right), and only then state-validity of the targeted entity against §3's state machines. After those four, domain-specific rules apply in the following order: the `STAT`-priority channel rule for critical notifications, the released-result protection on specimen rejection, the instrument-slot overlap check with `qc_buffer_minutes`, the per-collector five-minute spacing rule, the cross-reference rule that `Result.specimen_id` and `Result.lab_order_id` must agree on the parent order, the cross-reference rule that `Result.run_id` must reference an `InstrumentRun` whose `specimen_id` matches the result's `specimen_id`, the reference-range and critical-range sanity checks, the acknowledgement-window check, the acknowledgement-recipient check, the OCC stale-version checks, and finally the uniqueness checks on identifiers like `mrn`, `npi`, and `instrument_code`. A practical consequence is that an unauthenticated request never produces a state-transition error — the authentication check fires first — and a request that fails both an existence check and a domain check reports the existence failure.

## 3. Business Logic & Workflows

### 3.1. Patients, Clinicians, and the Bootstrap Sequence

A patient is registered with a medical record number (`mrn`) following the pattern `MRN-` followed by six uppercase alphanumeric characters, a legal `full_name`, and a `date_of_birth` expressed as an ISO 8601 date. The `mrn` is unique across the entire patient population — a duplicate is rejected with `ERR_DUPLICATE_IDENTIFIER`. At registration the system eagerly computes `age_band` from the supplied `date_of_birth` against the server's current clock: under twenty-eight days old yields `NEONATE`, under one year yields `INFANT`, under eighteen years yields `PEDIATRIC`, and at least eighteen years yields `ADULT`. The `age_band` is recomputed at every result release, so a child whose birthday falls between two releases for the same lab order may move from `PEDIATRIC` to `ADULT` between rows.

Clinicians are registered with a ten-digit `npi`, a `full_name`, a `role_type` drawn from `ORDERING_PROVIDER`, `PHLEBOTOMIST`, `LAB_TECH`, or `LAB_DIRECTOR`, and an E.164 `phone_e164` of the form `+` followed by a country digit one through nine and then one to fourteen additional digits. The `npi` is unique across the clinician population; a collision is rejected with `ERR_DUPLICATE_IDENTIFIER`. Every clinician whose `role_type` is not `LAB_DIRECTOR` MUST also supply a `backup_clinician_id` naming another clinician; omitting it is rejected with `ERR_BACKUP_REQUIRED`. The `backup_clinician_id` is the escalation target used by §3.5 when a notification is escalated past its deadline. Only a `LAB_DIRECTOR` may register with `backup_clinician_id` omitted.

Registration of clinicians is bootstrap-accessible: an `Anonymous` caller can create the very first `LabDirector` (since there is no parent director to authenticate against). After bootstrap, subsequent clinician registration is normally performed by an authenticated `LabDirector`, but either role is acceptable to the endpoint.

Two cross-role data-integrity rules are enforced wherever a clinician is named by foreign key. A `LabOrder` whose `ordering_clinician_id` does not reference a clinician with `role_type` equal to `ORDERING_PROVIDER` is rejected with `ERR_CLINICIAN_ROLE_MISMATCH`; the same error is returned when a `Specimen` is created with a `collector_clinician_id` whose underlying clinician has a `role_type` other than `PHLEBOTOMIST`.

Patient lookup, lab-order lookup scoped to a patient, and clinician lookup are read-mostly and shared across most authenticated roles per the §4 endpoint table.

### 3.2. Lab Order Lifecycle: From Draft to Resulted

A lab order begins life in `DRAFT` status when an `OrderingProvider` places it. The creation payload carries the `ordering_clinician_id` (which the system additionally checks against the role-type rule of §3.1), the `panel_code` selecting one of `CMP`, `CBC`, `TROP`, or `GLUC`, and an optional `priority` choosing between `STAT` (target turn-around at most sixty minutes) and `ROUTINE` (target turn-around at most two hundred and forty minutes); when omitted, `priority` defaults to `ROUTINE`. The server pins `ordered_at` to its current clock at the moment the order is created.

An order remains in `DRAFT` until either it is cancelled or one of its specimens is accessioned. Cancellation by the ordering provider transitions `DRAFT → CANCELLED` and, as a cascade, transitions every specimen of the order that is still in `DRAFT`, `COLLECTED`, or `IN_TRANSIT` to `REJECTED` with `reject_reason` set to `MISLABELED` — these specimens are treated as orphaned by the cancellation. Cancellation is only valid while the order is in `DRAFT` with no specimen yet accessioned; once any specimen has been accessioned, the order has crossed into `ACCESSIONED` and the cancel pathway is no longer available to the ordering provider. Such an attempt is rejected with `ERR_INVALID_STATE`.

The transition `DRAFT → ACCESSIONED` happens as a system-driven second hop when the first specimen of the order moves into `ACCESSIONED` (see §3.3). Both `specimens_count` and `accessioned_count` are recomputed before the cascade reads them. Once at least one `Result` on the order reaches `RELEASED`, the order transitions `ACCESSIONED → RESULTED` and the order's `turn_around_time_minutes` is pinned per §3.6. `RESULTED` and `CANCELLED` are terminal for `LabOrder`.

There is also a system-actor variant of cancellation: when a specimen rejection drops the order's `specimens_count` to zero while the order is in `ACCESSIONED`, the order is cascaded `ACCESSIONED → CANCELLED` by the system rather than by a human caller. If any `CriticalNotification` rows on this order's results are in `PENDING` or `SENT`, they cascade further to `VOIDED`.

### 3.3. Specimen Chain of Custody

Each specimen is registered against a parent lab order, supplying a `collector_clinician_id` and a `container_code` chosen from `RED` (serum), `LAVENDER` (EDTA whole blood), `GREEN` (heparin), or `GRAY` (fluoride). The specimen is born in `DRAFT` status. Custody then moves through four ordered events: collection at the patient's side (transitioning `DRAFT → COLLECTED`), hand-off to a courier (transitioning `COLLECTED → IN_TRANSIT`), arrival and accessioning at the lab (transitioning `IN_TRANSIT → ACCESSIONED`), and — at any later point if the specimen is found to be non-viable — rejection (transitioning to `REJECTED` from `COLLECTED`, `IN_TRANSIT`, or `ACCESSIONED`).

Collection is performed by the named `Phlebotomist`, and `X-User-ID` MUST equal the specimen's `collector_clinician_id`; a mismatch results in `ERR_UNAUTHORIZED`. The order itself MUST still be in `DRAFT` at the moment of collection. On success, the server pins `collected_at` to its current clock. Collection by the same `Phlebotomist` is rate-limited: if any other non-rejected specimen of theirs (in `COLLECTED`, `IN_TRANSIT`, or `ACCESSIONED`) was collected within five minutes of the new attempt, the new collection is rejected with `ERR_COLLECTOR_BUSY`. The semantics are point-collision against a buffered window — the new specimen's intended collection moment must fall outside a five-minute window around every prior non-rejected specimen of the same collector.

Hand-off to a courier transitions `COLLECTED → IN_TRANSIT`. Lab arrival transitions `IN_TRANSIT → ACCESSIONED`, performed by a `LabTech`; the server pins `accessioned_at` to its current clock. Accessioning the first specimen of an order in `DRAFT` is also the second-hop trigger for the order's transition `DRAFT → ACCESSIONED`. In all cases, `specimens_count` and `accessioned_count` are recomputed against the live specimen rows immediately after the transition.

Rejection requires a `reject_reason` drawn from `HEMOLYZED`, `CLOTTED`, `INSUFFICIENT_VOLUME`, or `MISLABELED`. Rejection of an `ACCESSIONED` specimen that has a `RELEASED` `Result` is forbidden, since that would orphan a clinically released finding; such an attempt is rejected with `ERR_RELEASED_RESULT_BLOCKS_REJECT` and the caller is directed to invalidate the result first (only a `LabDirector` may do so). When rejection succeeds and the post-recompute `specimens_count` of the parent order is zero, the order is cascaded `ACCESSIONED → CANCELLED` by the system; if that order had `CriticalNotification` rows in `PENDING` or `SENT`, those are cascaded further to `VOIDED`.

### 3.4. Instruments, Run Scheduling, and Slot Conflicts

Instruments are the physical analyzers that consume specimens and emit measurements. Each is registered by a `LabDirector` with a stable `instrument_code`, an array of supported panels (`analyte_panels_supported`, drawn from the same `CMP`, `CBC`, `TROP`, `GLUC` set used for orders), and an optional `qc_buffer_minutes` representing the mandatory cooldown between consecutive runs. The `qc_buffer_minutes` defaults to five and is constrained to the inclusive range zero through sixty. The `instrument_code` is unique across the instrument fleet; a duplicate is rejected with `ERR_DUPLICATE_IDENTIFIER`.

An `InstrumentRun` is scheduled by a `LabTech` against a specific `instrument_id` and `specimen_id`, with a planned half-open booking window of `scheduled_start` (inclusive) up to but not including `scheduled_end` (exclusive). The `scheduled_end` MUST be strictly greater than `scheduled_start`. The specimen referenced by `specimen_id` MUST be in `ACCESSIONED` status at the moment of scheduling. The run is born in `SCHEDULED` status; subsequent operation by the lab transitions it to `IN_PROGRESS`, then to `COMPLETED` (or `FAILED`); only a run in `COMPLETED` status may have a `Result` released against it.

Two runs on the same instrument MUST NOT overlap once each existing run's interval is widened by the instrument's `qc_buffer_minutes` on either side. Concretely, an existing run with interval `[A, B)` is treated, for overlap purposes, as occupying `[A − qc_buffer_minutes, B + qc_buffer_minutes)`, and the proposed run's `[scheduled_start, scheduled_end)` must be disjoint from every such buffered window for every existing run in `SCHEDULED`, `IN_PROGRESS`, or `COMPLETED`. A conflict is rejected with `ERR_INSTRUMENT_SLOT_CONFLICT`. This check is per-instrument: two runs on different instruments do not interact regardless of their windows.

### 3.5. Releasing Results and the Critical-Value Loop

A `Result` row is created in `PROVISIONAL` status by a `LabTech` and carries every input the lab system needs to interpret it: `lab_order_id`, `specimen_id`, `run_id`, `analyte_code` (one of `K`, `GLUCOSE`, `TROPONIN`, `HGB`), `numeric_value` (to two decimal places), `unit` (which must match the canonical unit for the analyte — for example, potassium in `mmol/L`), and the four range bounds `reference_low`, `reference_high`, `critical_low`, `critical_high`. The references MUST satisfy `reference_high > reference_low` AND `critical_high > critical_low`; a violation is rejected with `ERR_INVALID_RANGE`. The `specimen_id` and `lab_order_id` MUST agree on the parent order — that is, the named specimen's own `lab_order_id` MUST equal the supplied `lab_order_id` — or the create is rejected with `ERR_SPECIMEN_ORDER_MISMATCH`. Additionally, the `run_id` MUST reference an `InstrumentRun` whose `specimen_id` equals the result's own `specimen_id`; a mismatch is rejected with `ERR_RUN_SPECIMEN_MISMATCH`.

Releasing a result transitions it from `PROVISIONAL` to `RELEASED`. The release call carries `expected_lab_order_version` per §2.6. The specimen named by the result MUST be in `ACCESSIONED` status and the instrument run named by the result MUST be in `COMPLETED` status; otherwise the release is rejected with `ERR_INVALID_STATE`. On success, `released_at` is pinned to the server clock and `criticality` is computed; if the result is the first releasable result on the order, the parent order transitions `ACCESSIONED → RESULTED` and `turn_around_time_minutes` is computed (see §3.6 for both calculations). The patient's `results_release_count` is incremented by one. The order's `version` is incremented as part of the cascade — which is exactly the bump that will cause any peer release operating from a stale read of the order to fail with `ERR_STALE_LAB_ORDER_VERSION`.

Criticality is classified by a two-stage rule. First, a base tier is computed from the numeric value against the range bounds: a `numeric_value` at or below `critical_low` yields `CRITICAL_LOW`, a `numeric_value` at or above `critical_high` yields `CRITICAL_HIGH`, a `numeric_value` strictly below `reference_low` or strictly above `reference_high` (but still inside the critical band) yields `ABNORMAL`, and otherwise `NORMAL`. Second, a `NEONATE` override is applied: when the patient's `age_band` is `NEONATE`, a potassium reading (`analyte_code` of `K`) at or above 6.50 mmol/L OR at or below 2.50 mmol/L immediately classifies as `PANIC` regardless of the base tier; and a glucose reading (`analyte_code` of `GLUCOSE`) at or below 40.00 mg/dL likewise classifies as `PANIC`. `PANIC` supersedes any `CRITICAL_LOW`, `CRITICAL_HIGH`, or `ABNORMAL` base tier. For patients whose `age_band` is `INFANT`, `PEDIATRIC`, or `ADULT`, no `PANIC` override applies and the result's `criticality` is whatever the base tier produced — `PANIC` is unreachable for non-neonates. Note that this means the same `numeric_value`, `analyte_code`, and range bounds can yield a different `criticality` for two patients whose only difference is their `age_band`.

When the computed `criticality` is `CRITICAL_LOW`, `CRITICAL_HIGH`, or `PANIC`, the release additionally auto-creates a single `CriticalNotification` row with `status` set to `PENDING`. Its `recipient_clinician_id` is the parent order's `ordering_clinician_id` at the moment of release, and its `channel` is selected by the integration tier based on order priority (see §3.7 for the safety constraint). For non-critical results (`NORMAL` or `ABNORMAL`), no notification is created.

### 3.6. Turn-Around-Time Computation

A lab order's `turn_around_time_minutes` is computed when the first result on the order is released. The system computes it in two flavors. The default flavor, which is what `turn_around_time_minutes` is pinned to on the order, is `clinical_chronology`: the integer minutes between `ordered_at` and the earliest `released_at` of any released result on the order, computed by subtracting the two timestamps, expressing the gap in seconds, dividing by sixty, and truncating any fractional minute toward zero (floor). The alternative flavor, `lab_processing`, spans the earliest `accessioned_at` of any accessioned specimen of the order to the earliest `released_at`; it excludes the pre-analytic transit and accessioning time and therefore yields a smaller value than `clinical_chronology` for the same underlying timestamps. The alternative flavor is not stored on the order; it is computed on demand and surfaced through the lab-order read endpoint when the client supplies a `tat_variant` query parameter naming `lab_processing` (the default `tat_variant`, omitted or set to `clinical_chronology`, returns the stored value).

### 3.7. Notification Delivery, Acknowledgement, and Escalation

A pending notification is delivered by a `LabTech` (acting as the integration operator), which transitions it from `PENDING` to `SENT`. The `channel` selected for delivery — either `SMS` or `PHONE` — drives the deadline mechanics. When the underlying `LabOrder`'s `priority` is `STAT`, the `channel` MUST be `PHONE`; an `SMS` delivery attempt on a `STAT` order is rejected with `ERR_STAT_REQUIRES_PHONE_CHANNEL`, because CLIA documentation policy requires voice contact for the most time-critical orders. On a `ROUTINE` order either channel is acceptable.

When the send succeeds, the server pins `sent_at` to its current clock, increments `attempt_count` by one (initial sends and retries both count toward `attempt_count`), and computes `ack_deadline_at`. For a `PHONE` channel, `ack_deadline_at` equals `sent_at` plus exactly thirty minutes; for an `SMS` channel, it equals `sent_at` plus exactly sixty minutes. The first time a notification reaches `SENT`, the patient's `critical_incidents_count` is incremented by one; subsequent retries do not re-increment it, and voiding or escalation never decrements it.

The notification is then expected to be acknowledged by the ordering provider whose id is captured in `recipient_clinician_id`. Acknowledgement is performed by submitting an attestation, which both transitions the notification from `SENT` to `ACKNOWLEDGED` and persists an immutable `AcknowledgementReceipt` row. The receipt carries the `critical_notification_id` of the notification, the `acknowledging_clinician_id` (taken from the request's `X-User-ID`), an `ack_method` chosen from `SMS_REPLY`, `IVR_KEYPRESS`, or `WEB_UI`, and an `attestation_text` free-text field that is mandatory for CLIA documentation and must be between one and five hundred characters in length.

Two ownership and timing rules guard the acknowledgement. The acknowledging caller MUST be the named recipient — `X-User-ID` MUST equal the notification's `recipient_clinician_id`, or the attempt is rejected with `ERR_ACK_WRONG_RECIPIENT`. The server's current clock MUST be at most `ack_deadline_at` — an attempt at exactly the deadline succeeds, but an attempt one minute past the deadline is rejected with `ERR_ACK_WINDOW_CLOSED`.

If the deadline passes without an acknowledgement, the notification can be escalated by a `LabTech`. Escalation is only valid when the notification is in `SENT` status, the server clock is strictly past `ack_deadline_at`, and the recipient clinician has a non-null `backup_clinician_id`. On success the notification transitions to `ESCALATED`, the `escalation_target_clinician_id` is pinned to the recipient's `backup_clinician_id` at that moment, `attempt_count` is incremented, and — as the second hop of this cascade — the parent `LabOrder`'s `compliance_incident` is raised to true and remains true for the remainder of the order's life. `ACKNOWLEDGED`, `ESCALATED`, and `VOIDED` are terminal for `CriticalNotification`.

System cascades may also force a notification into `VOIDED` without operator action: a `PENDING` or `SENT` notification is voided when its parent `Result` is invalidated by the lab director, when the parent `Result` is amended (a fresh notification is then auto-created on the new released row if its recomputed criticality is still critical), and when the parent `LabOrder` is system-cancelled because all of its specimens have been rejected.

### 3.8. Amendments, Invalidations, and the Retest Workflow

Amending a result is reserved for the situation in which the lab has determined that the released numeric value was wrong and a corrected value must be released without erasing the prior row. The amend call carries `expected_result_version` per §2.6 and a fresh `numeric_value`. On success, the existing row is marked `AMENDED` (preserved for the audit trail) and a new row is inserted in `RELEASED` status, identical to the prior row in `lab_order_id`, `specimen_id`, and `run_id`, with `amended_from_result_id` pointing back to the prior row (this is the self-referential foreign key that forms the amendment chain). The new row's `criticality` is freshly classified against the recomputed `age_band` of the patient. The patient's `results_release_count` does not change on amendment — the old row leaves `RELEASED` (entering `AMENDED`) at the same time the new row enters `RELEASED`, for a net zero. Any prior `CriticalNotification` on the old row that is still in `PENDING`, `SENT`, or `ACKNOWLEDGED` is marked `VOIDED`, and a fresh notification is auto-created on the new row when the recomputed criticality is `CRITICAL_LOW`, `CRITICAL_HIGH`, or `PANIC`.

Invalidating a result is the lab director's prerogative: only a clinician whose `role_type` is `LAB_DIRECTOR` may transition a result from `RELEASED` to `INVALIDATED`. On success the patient's `results_release_count` is decremented by one, and any `CriticalNotification` on the result in `PENDING` or `SENT` is voided. `INVALIDATED` is terminal for `Result`.

The retest workflow lets an ordering provider request a fresh measurement when they doubt a previously released finding. The provider opens a retest with a `reason` of `DELTA_CHECK_FAIL`, `CLINICIAN_DOUBT`, or `INSTRUMENT_QC_FAIL` against a result whose `status` is `RELEASED` or `AMENDED` — the system records the request's `original_result_id` and the new request lives in `REQUESTED`. The lab then schedules the retest, at which point the system auto-creates a fresh `LabOrder` whose `patient_id` and `ordering_clinician_id` are copied from the original order and whose `panel_code` is copied as well, with the new order's `priority` set to `STAT` regardless of the original's priority; the retest's `new_order_id` is then pinned to the new order's id and the retest transitions `REQUESTED → SCHEDULED`. When the new order itself reaches `RESULTED`, the lab marks the retest `SCHEDULED → COMPLETED`. The ordering provider may also abandon an unscheduled retest, transitioning it `REQUESTED → CANCELLED`. `COMPLETED` and `CANCELLED` are terminal.

### 3.9. Administrative Clock Control

For deterministic exercise of the deadline mechanics described in §3.4 (slot overlap relative to `qc_buffer_minutes`), §3.5 (collection rate limit), and §3.7 (acknowledgement window relative to `ack_deadline_at`), the system exposes an admin-only test-driving capability that pins the server's logical UTC clock to a supplied `to_iso8601` instant. The capability is restricted to `LabDirector`. Subsequent server-clock reads (the ones that populate `ordered_at`, `collected_at`, `accessioned_at`, `released_at`, `sent_at`, and that drive the at-most-`ack_deadline_at` check on acknowledgement) use this pinned clock until reset.

## 4. Endpoint Definitions

The endpoint table below summarizes the HTTP surface. New resources are returned with HTTP 201; state transitions and other modifications are returned with HTTP 200. List endpoints page per §2.3, and per-endpoint request and response shapes are reconstructed from the workflow narratives in §3. Foreign-key reverse-reachability list filters (e.g., filtering critical notifications by `recipient_clinician_id` or `escalation_target_clinician_id`) are noted in the descriptions where they apply.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | /patients | Register a patient. | LabTech, LabDirector |
| GET | /patients/{id} | Read a patient by id. | LabTech, LabDirector, OrderingProvider, Phlebotomist |
| GET | /patients | List patients with optional `mrn` filter. | LabTech, LabDirector, OrderingProvider |
| GET | /patients/{id}/lab-orders | List lab orders for a patient. | LabTech, LabDirector, OrderingProvider |
| POST | /clinicians | Register a clinician. Bootstrap-accessible to `Anonymous`. | Anonymous, LabDirector |
| GET | /clinicians/{id} | Read a clinician. | LabTech, LabDirector, OrderingProvider, Phlebotomist |
| GET | /clinicians | List clinicians with optional `role_type` and `backup_clinician_id` filters. | LabTech, LabDirector, OrderingProvider |
| POST | /patients/{patient_id}/lab-orders | Create a new lab order for a patient. | OrderingProvider |
| GET | /lab-orders/{id} | Read a lab order; optional `tat_variant` query selects the TAT flavor. | LabTech, LabDirector, OrderingProvider |
| GET | /lab-orders | List lab orders with optional `patient_id`, `ordering_clinician_id`, `status` filters. | LabTech, LabDirector, OrderingProvider |
| POST | /lab-orders/{id}/cancel | Cancel a draft lab order. | OrderingProvider |
| POST | /lab-orders/{order_id}/specimens | Register a specimen for a lab order. | Phlebotomist, LabTech |
| GET | /specimens/{id} | Read a specimen. | LabTech, LabDirector, OrderingProvider, Phlebotomist |
| GET | /specimens | List specimens with optional `lab_order_id`, `collector_clinician_id`, `status` filters. | LabTech, LabDirector, OrderingProvider, Phlebotomist |
| POST | /specimens/{id}/collect | Record specimen collection. | Phlebotomist |
| POST | /specimens/{id}/transit | Hand specimen to courier. | Phlebotomist |
| POST | /specimens/{id}/accession | Lab accessions the specimen. | LabTech |
| POST | /specimens/{id}/reject | Reject a specimen with a reason. | LabTech |
| POST | /instruments | Register a lab analyzer. | LabDirector |
| GET | /instruments/{id} | Read an instrument. | LabTech, LabDirector |
| GET | /instruments | List instruments. | LabTech, LabDirector |
| POST | /instrument-runs | Schedule an instrument run. | LabTech |
| GET | /instrument-runs/{id} | Read an instrument run. | LabTech, LabDirector |
| GET | /instrument-runs | List instrument runs with optional `instrument_id`, `specimen_id`, `status` filters. | LabTech, LabDirector |
| POST | /instrument-runs/{id}/complete | Mark an instrument run as `COMPLETED`. | LabTech |
| POST | /results | Create a Result in `PROVISIONAL`. | LabTech |
| GET | /results/{id} | Read a Result. | LabTech, LabDirector, OrderingProvider |
| GET | /results | List Results with optional `lab_order_id`, `specimen_id`, `run_id`, `amended_from_result_id`, `status` filters. | LabTech, LabDirector, OrderingProvider |
| POST | /results/{id}/release | Release a Result; OCC via `expected_lab_order_version`. | LabTech |
| POST | /results/{id}/amend | Amend a released Result; OCC via `expected_result_version`. | LabTech |
| POST | /results/{id}/invalidate | Invalidate a released Result. | LabDirector |
| GET | /critical-notifications/{id} | Read a critical notification. | LabTech, LabDirector, OrderingProvider |
| GET | /critical-notifications | List critical notifications with optional `result_id`, `recipient_clinician_id`, `escalation_target_clinician_id`, `status` filters. | LabTech, LabDirector, OrderingProvider |
| POST | /critical-notifications/{id}/send | Deliver a notification (`PENDING → SENT`). | LabTech |
| POST | /critical-notifications/{id}/escalate | Escalate an unacknowledged notification (`SENT → ESCALATED`). | LabTech |
| POST | /critical-notifications/{id}/acknowledgements | Capture an acknowledgement receipt. | OrderingProvider |
| GET | /critical-notifications/{id}/acknowledgements | List acknowledgement receipts for a notification. | LabTech, LabDirector, OrderingProvider |
| GET | /acknowledgement-receipts/{id} | Read a single acknowledgement receipt. | LabTech, LabDirector, OrderingProvider |
| GET | /acknowledgement-receipts | List acknowledgement receipts with optional `critical_notification_id`, `acknowledging_clinician_id` filters. | LabTech, LabDirector, OrderingProvider |
| POST | /results/{id}/retest-requests | Open a retest request against a released or amended Result. | OrderingProvider |
| GET | /retest-requests/{id} | Read a retest request. | LabTech, LabDirector, OrderingProvider |
| GET | /retest-requests | List retest requests with optional `original_result_id`, `new_order_id`, `status` filters. | LabTech, LabDirector, OrderingProvider |
| POST | /retest-requests/{id}/schedule | Schedule the retest and auto-create a STAT lab order. | LabTech |
| POST | /retest-requests/{id}/cancel | Cancel an unscheduled retest request. | OrderingProvider |
| POST | /_clock/set_current_utc | Pin the server's UTC clock to a supplied `to_iso8601` instant. | LabDirector |

## 5. Error Code Catalogue

The trigger conditions for each error are described in §2 and §3 alongside the workflow they guard; the table records only the identifier and its HTTP status.

| Error ID | HTTP Status Code |
| --- | --- |
| ERR_UNAUTHENTICATED | 401 |
| ERR_UNAUTHORIZED | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_INVALID_STATE | 409 |
| ERR_INVALID_REQUEST | 400 |
| ERR_DUPLICATE_IDENTIFIER | 409 |
| ERR_STAT_REQUIRES_PHONE_CHANNEL | 422 |
| ERR_RELEASED_RESULT_BLOCKS_REJECT | 409 |
| ERR_INSTRUMENT_SLOT_CONFLICT | 409 |
| ERR_COLLECTOR_BUSY | 409 |
| ERR_SPECIMEN_ORDER_MISMATCH | 422 |
| ERR_RUN_SPECIMEN_MISMATCH | 422 |
| ERR_INVALID_RANGE | 422 |
| ERR_ACK_WINDOW_CLOSED | 409 |
| ERR_ACK_WRONG_RECIPIENT | 403 |
| ERR_STALE_LAB_ORDER_VERSION | 412 |
| ERR_STALE_RESULT_VERSION | 412 |
| ERR_CLINICIAN_ROLE_MISMATCH | 422 |
| ERR_BACKUP_REQUIRED | 422 |
