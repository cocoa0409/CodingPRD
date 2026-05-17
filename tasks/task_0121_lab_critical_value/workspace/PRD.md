# Lab Critical Value API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the Laboratory Results and Critical Value Notification API, a system that governs the end-to-end journey of a laboratory test — from order entry, through specimen collection and a multi-leg chain-of-custody transport, into result production, release, and the time-bounded delivery of critical-value notifications. The system is designed to satisfy CLIA (Clinical Laboratory Improvement Amendments) compliance obligations: strict segregation of duties between the clinician who produces a result and the one who releases it, complexity-based authorization for resulting, mandatory read-back acknowledgement of critical values for high-complexity panels, and a tamper-evident audit trail for every clinically significant event.

The operational pain point this system addresses is the silent failure mode of conventional lab pipelines, where a critical out-of-range result can sit unread for hours while a patient deteriorates. The platform turns that risk into a tracked workflow: every critical result automatically opens a notification with a deterministic acknowledgement deadline derived from order priority, escalates from SMS to voice when the deadline lapses, and — failing all attempts — auto-issues a retest so no actionable value is ever lost. The same machinery records each step in a compliance log that the Lab Director can later inspect.

The API serves three coordinated user populations: ordering providers who place and cancel orders and who acknowledge critical notifications for their own patients, lab technicians who perform collection and transport handoffs and (within complexity limits) produce results, and lab directors who oversee the lab, register clinicians, define panels, release and amend results, and operate the sweep and clock-control mechanisms used in testing and recovery.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request to the API must carry two mandatory HTTP headers: `X-User-ID`, which identifies the acting user, and `X-User-Role`, which declares the operational capacity in which the request is made. Requests missing either header, or carrying an empty value for either, are rejected with `ERR_AUTH_REQUIRED`. When the headers are present but the declared role is not permitted to invoke the requested endpoint, the request is rejected with `ERR_FORBIDDEN`.

The system recognizes exactly three roles: `OrderingProvider`, `LabTech`, and `LabDirector`. All three roles are entity-backed by the `Clinician` table: when `X-User-Role` is `OrderingProvider`, `LabTech`, or `LabDirector`, `X-User-ID` is the `id` of the acting `Clinician`, and ownership checks on any resource that references a `Clinician` compare the resource's foreign-key field to `X-User-ID`. In practice this means that an `OrderingProvider` cancelling an order has its `X-User-ID` checked against that order's `ordering_provider_id`, an acknowledger has its `X-User-ID` checked against the notification's `recipient_clinician_id`, and the `Clinician` referenced by a write must be currently active. The role declared in `X-User-Role` must also be consistent with the `role_kind` recorded on the underlying `Clinician` row for any operation that has a `role_kind`-specific precondition (for example, a `LabTech` actor's `Clinician` row must have `role_kind` equal to `LAB_TECH`).

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter caps the number of items returned and defaults to 10 when omitted, with a minimum permitted value of 1 and a maximum permitted value of 100. The `offset` parameter specifies the number of items to skip from the front of the result set and defaults to 0; values below 0 are not accepted. Pagination parameters outside these bounds are rejected with `ERR_INVALID_PAGINATION`.

Unless a specific endpoint declares otherwise, list endpoints return resources sorted by their creation timestamp in ascending order. List responses include the fields `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the response envelope.

### 2.4. Common Resource Properties

All primary, top-level resources (such as `Patient`, `Clinician`, `TestPanel`, `LabOrder`, `Specimen`, `LabResult`, `CriticalNotification`, and `RetestRequest`) carry a standard set of system-managed fields:

- **`id` (string):** A server-minted UUID with no type prefix; unique across the resource family.
- **`created_at` (string):** An ISO 8601 timestamp in UTC with three fractional digits indicating when the row was first persisted.
- **`updated_at` (string):** An ISO 8601 UTC timestamp with three fractional digits indicating when the row was last mutated. The system bumps `updated_at` on every persisted state transition or field change.
- **`version` (integer):** A system-managed integer that begins at 1 on creation and is incremented by exactly 1 on every persisted mutation. It supports the optimistic concurrency control mechanism described in §2.10.

Two entities in this domain are immutable after creation and therefore carry only `id` and `created_at`; both `updated_at` and `version` are absent on these. They are `TransportLeg` (whose subsequent `status` transitions create no separate update event on the leg row itself for OCC purposes — see §3 for transport-handoff semantics — but whose authored fields are recorded once and not subject to OCC) and `AcknowledgementReceipt` (which is append-only and is never mutated after the acknowledgement is recorded). `ComplianceAuditEvent` is likewise append-only and carries only `id` and `created_at`; an audit event row is never modified after it is written.

### 2.5. Nested Resource Retrieval

The API enforces strict left-to-right path validation for any endpoint whose URL contains more than one identifier segment. The server resolves each `{id}` segment in the order it appears in the path, and the first segment that fails to resolve to a live row terminates the request with `ERR_NOT_FOUND`. For example, a request that targets a transport leg below a specimen will first confirm the existence of the specimen identified in the path before attempting to locate the leg, and the same ordering applies to lab-order, specimen, transport-leg, result, notification, and retest-request hierarchies. Body-referenced foreign keys are likewise resolved before any state or business check; when `POST /lab-orders` is invoked with a `patient_id`, `ordering_provider_id`, or `panel_id` that does not resolve, the same `ERR_NOT_FOUND` is returned, as it is for unresolved `collected_by_id`, `resulted_by_id`, `released_by_id`, or `acknowledged_by_id` on their respective endpoints.

### 2.6. The CLIA Compliance and Segregation-of-Duties Principle

The system enforces three Clinical Laboratory Improvement Amendments (CLIA) obligations as cross-cutting principles. First, **complexity-tiered authorization for resulting**: a `TestPanel` carries a `clia_complexity` of `WAIVED`, `MODERATE`, or `HIGH`, and the clinician who produces the result (named in `resulted_by_id`) must have a `role_kind` of `LAB_TECH` or `LAB_DIRECTOR` for `WAIVED` and `MODERATE` panels, and must have a `role_kind` of `LAB_DIRECTOR` for `HIGH` panels. A violation of this rule is rejected with `ERR_CLIA_COMPLEXITY_VIOLATION`. Second, **segregation of duties on release**: the clinician named in `released_by_id` must have `role_kind` equal to `LAB_DIRECTOR`, must be `active`, and must be a different clinician from the one named in `resulted_by_id`; if `released_by_id` equals `resulted_by_id` the release is rejected with `ERR_CLIA_SOD_VIOLATION`. Third, **mandatory read-back of critical values for high-complexity panels**: when acknowledging a notification for a `HIGH`-complexity panel, the `read_back_text` field must contain each `analyte_code` from the result's `critical_flags`, compared case-insensitively as a substring match; a missing analyte code in the read-back is rejected with `ERR_READBACK_INCOMPLETE`. These rules are evaluated in addition to the standard role check from §2.1.

Every clinician participating in a write — the `ordering_provider_id` on order placement, the `collected_by_id` on specimen collection, the `resulted_by_id` on resulting, and the `released_by_id` on release — must have `active` equal to `true` on the underlying `Clinician` row. A reference to an inactive clinician is rejected with `ERR_CLINICIAN_INACTIVE`.

### 2.7. Patient Consent and Notification Eligibility

A `Patient` row carries a `notification_consent` value of `SMS_AND_VOICE`, `VOICE_ONLY`, or `NONE` (defaulting to `SMS_AND_VOICE` when omitted at creation). The patient's `primary_phone_e164` is the destination of the first SMS attempt for any critical notification, and the optional `backup_phone_e164` exists for downstream voice escalation. When releasing a result that would, by virtue of containing critical flags, require the system to open a `CriticalNotification`, the patient's `notification_consent` must permit some form of contact: a value of `NONE` blocks the release, which is rejected with `ERR_PATIENT_CONSENT_BLOCKED`. Releases for a result with no critical flags are unaffected by the consent setting because no notification is opened.

### 2.8. Time-Order and Chain-of-Custody Invariants

Any timestamp the client supplies must respect physical causality. The collection timestamp `collected_at` on a specimen creation must be at or before the server's current clock. Within a transport leg, the leg's `arrived_at` must be at or later than its `departed_at`; and across the leg sequence, the first leg's `departed_at` must be at or later than the specimen's `collected_at`. Any violation of these orderings is rejected with `ERR_TIME_ORDER_INVALID`.

The transport chain itself must be monotonic and contiguous. When a new leg is opened on a specimen via the leg-creation endpoint, its `leg_index` must be exactly one greater than the maximum existing `leg_index` on that specimen, and its `from_location` must equal the previous leg's `to_location`. A break in this chain is rejected with `ERR_TRANSPORT_CHAIN_BROKEN`. The previous leg must also itself be in the `ARRIVED` state before a new leg may be opened; an attempt to open a new leg while a prior leg is still `DEPARTED` is the same chain-monotonicity violation and is reported with the same `ERR_TRANSPORT_CHAIN_BROKEN`.

### 2.9. Precision and Time Arithmetic

Every calculation that produces a number for storage or response is performed in decimal arithmetic. The two severity-score calculations (described in §3) round to exactly 2 decimal places using the "round half up" rule; the variant difference is the round-then-sum versus sum-then-round ordering described in §3, not the precision or rounding mode. The acknowledgement-latency value `ack_latency_minutes` is computed in minutes to 2 decimal places. Transit-minute arithmetic used by the specimen stability check is performed at 4 fractional digits; the stability comparison is strict — transit minutes equal to the panel's `stability_minutes` is considered on-time and accepted, and only transit minutes strictly greater than `stability_minutes` cause a rejection. Critical-flag comparisons against the panel's per-analyte `critical_low` and `critical_high` are likewise performed at 4 fractional digits without prior rounding.

### 2.10. Optimistic Concurrency Control

Endpoints that mutate an existing resource accept an optional `version` field in the request body. When the client supplies `version`, the server compares it to the current `version` of the targeted resource; a mismatch is rejected with `ERR_VERSION_CONFLICT`. When the client omits `version`, the server processes the mutation without an OCC check. On every persisted mutation — including state transitions, cascaded child or parent updates, and recomputations — the server bumps `updated_at` and increments `version` by exactly 1 on each mutated row.

### 2.11. Cascading Effects, Sweeps, and the System Actor

Many state transitions in this domain cascade to related rows. Marking the final transport leg as arrived may flip the specimen and the lab order; reporting a broken chain flips the specimen, the lab order, and creates a fresh replacement order; releasing a result with critical flags creates a notification and writes two audit events. These cascades are described in §3 alongside the workflows that trigger them. Some transitions are not triggered by a clinician at all — the notification escalation from `SMS` to `VOICE` and the eventual transition to `FAILED` are performed by the sweep, which advances on operator demand. When the sweep performs a state transition, the `actor_id` recorded on the resulting `ComplianceAuditEvent` is the literal string `"system"` rather than a `Clinician.id`.

### 2.12. Concurrency Outcomes

Several mutating operations may be invoked concurrently for the same resource. In every such race the system serializes the contenders so that exactly one wins, and the loser receives a specific, predictable `error_id`:

- Two simultaneous release attempts on the same `DRAFT` `LabResult` serialize on the result's `status` flip from `DRAFT` to `RELEASED`; the first writer wins and the second is rejected with `ERR_INVALID_STATE`.
- A sweep-driven escalation race against the recipient's acknowledgement attempt is resolved on the notification's `status`: if the acknowledgement lands first, the notification transitions to `ACKNOWLEDGED` and the concurrent sweep silently skips the row (no escalation occurs and no audit event for an escalation is written); if the sweep transitions the notification to `ESCALATED` first, a subsequent acknowledgement against `ESCALATED` is still accepted because acknowledgement is permitted from both `PENDING` and `ESCALATED`. A second acknowledgement attempt landing after the notification has already reached `ACKNOWLEDGED` is rejected with `ERR_ALREADY_ACKNOWLEDGED`, which is distinct from the generic state error. An audit event already written for the earlier escalation is not rolled back when a late acknowledgement wins.
- Two simultaneous arrival reports on the same transport leg serialize on the leg's `status` flip from `DEPARTED` to `ARRIVED`; the first writer wins and the second is rejected with `ERR_LEG_ALREADY_ARRIVED`.
- An amendment attempt and a retraction attempt racing on the same `RELEASED` `LabResult` serialize on the result's `status`; the first writer wins and the second is rejected with `ERR_INVALID_STATE`.
- Two simultaneous specimen-creation attempts against the same `LabOrder` serialize on the uniqueness of `Specimen.lab_order_id`; the first writer wins and the second is rejected with `ERR_SPECIMEN_ALREADY_EXISTS`.

### 2.13. Validation Ordering

When a request would fail more than one rule simultaneously, the system evaluates rules in a fixed priority and returns the first violation it finds. The order, from highest priority to lowest, is: authentication header presence (`ERR_AUTH_REQUIRED`), role permission for the endpoint (`ERR_FORBIDDEN`), path-segment existence (`ERR_NOT_FOUND`), body-referenced foreign-key existence (`ERR_NOT_FOUND`), target-resource state validity for the requested transition (`ERR_INVALID_STATE`), then the business-safety rules in this order — segregation of duties (`ERR_CLIA_SOD_VIOLATION`), CLIA complexity tiering (`ERR_CLIA_COMPLEXITY_VIOLATION`), patient consent (`ERR_PATIENT_CONSENT_BLOCKED`) — then the business-referential rules in this order — acknowledger-recipient identity (`ERR_ACK_BY_WRONG_RECIPIENT`), read-back completeness (`ERR_READBACK_INCOMPLETE`) — then the business-constraint rules in this order — time ordering (`ERR_TIME_ORDER_INVALID`), transport-chain monotonicity (`ERR_TRANSPORT_CHAIN_BROKEN`), measurement coverage (`ERR_MEASUREMENTS_INCOMPLETE`), clinician active status (`ERR_CLINICIAN_INACTIVE`) — then the business-temporal rule for double acknowledgement (`ERR_ALREADY_ACKNOWLEDGED`), then optimistic concurrency (`ERR_VERSION_CONFLICT`), and finally pagination-parameter validity on list reads (`ERR_INVALID_PAGINATION`). Generic malformed-input failures — invalid E.164 phone strings, ill-formed ISO 8601 timestamps, missing required body fields, regex failures on `mrn` (which must match the format of two uppercase letters followed by eight digits) or `npi` (ten digits) or `code` (3 to 20 uppercase letters, digits, or underscores) — are reported with `ERR_VALIDATION`.

## 3. Business Logic & Workflows

### 3.1. Patients, Clinicians, and Panels: The Reference Catalogue

Before any order can be placed, the catalogue resources must exist. A `Patient` is created by either an `OrderingProvider` or a `LabDirector`. Each patient is identified externally by `mrn`, the medical record number, which must be unique across patients and conform to the format of two uppercase letters followed by eight digits. The body also carries `full_name`, `date_of_birth` as an ISO 8601 date in `YYYY-MM-DD` form, and `primary_phone_e164` formatted as a leading `+`, a leading non-zero digit, and 6 to 14 further digits. The optional `backup_phone_e164` follows the same E.164 format when supplied and defaults to absent. The optional `notification_consent` defaults to `SMS_AND_VOICE` and may be set to `VOICE_ONLY` or `NONE`.

A `Clinician` is registered exclusively by a `LabDirector` with the fields `npi` (the National Provider Identifier, ten digits, unique across clinicians), `full_name`, `role_kind` (one of `ORDERING_PROVIDER`, `LAB_TECH`, `LAB_DIRECTOR`), and `phone_e164` (in the same E.164 format as patient phones). A new clinician is active by default; a `LabDirector` may later toggle the `active` flag or update `phone_e164` on an existing clinician, optionally supplying `version` for OCC.

A `TestPanel` is defined exclusively by a `LabDirector` with `code` (a LOINC-style identifier 3 to 20 characters drawn from uppercase letters, digits, and underscores; unique across panels), `name`, `clia_complexity` (`WAIVED`, `MODERATE`, or `HIGH`), `specimen_type` (`BLOOD`, `URINE`, `CSF`, or `SWAB`), `stability_minutes` (a positive integer giving the maximum minutes the specimen may spend in transit before being rejected at lab receipt), and `analytes`. The `analytes` field is an ordered list, each element of which carries an `analyte_code`, a `unit`, and two nullable bounds `critical_low` and `critical_high`. Bounds may individually be null to express a one-sided critical range; when both bounds are present, `critical_low` must be less than `critical_high`.

Each catalogue resource is also fetchable by id, and patients may be listed with an optional `mrn` substring filter alongside `limit` and `offset`. Lab orders may be listed with optional `status`, `patient_id`, and `panel_id` filters.

### 3.2. Placing and Cancelling a Lab Order

Order placement is the entry point of the workflow. An `OrderingProvider` places an order by supplying a `patient_id`, an `ordering_provider_id`, a `panel_id`, and an optional `priority` of `ROUTINE` (default) or `STAT`. The supplied `ordering_provider_id` must reference a `Clinician` whose `role_kind` is `ORDERING_PROVIDER` and whose `active` flag is `true`. On success the new `LabOrder` is persisted with `status` set to `ORDERED` (the initial state for every order), `retest_count` set to 0, `parent_order_id` set to absent, and `ordered_at` set to a snapshot of the server clock at the moment of acceptance. A `ComplianceAuditEvent` with `event_type` of `ORDER_PLACED` is appended on creation; its `lab_order_id` is the new order's id, `actor_id` is the placing provider's id, and `payload` carries an event-specific JSON snapshot.

An `OrderingProvider` may cancel their own `ORDERED` order, optionally supplying `version` for OCC. The actor's id (the value of `X-User-ID`) must equal the order's `ordering_provider_id`; otherwise the request is rejected on the role-permission rule. Cancellation is permitted only while the order remains in `ORDERED`; any later state — `COLLECTED`, `IN_TRANSIT`, `RECEIVED`, `RESULTED`, `RELEASED`, `CANCELED`, or `REJECTED` — yields the standard state-violation rejection.

### 3.3. Collection, Transport, and Specimen Receipt

A `LabTech` records collection on an `ORDERED` order by supplying a `collected_by_id` and a `collected_at`. The supplied `collected_by_id` must reference a `Clinician` with `role_kind` of `LAB_TECH` who is currently `active`, and the order must still be in `ORDERED`. The `collected_at` timestamp must be at or before the server's current clock; a future-dated collection is rejected on time-order grounds. A successful collection creates a `Specimen` whose `lab_order_id` references the order, whose `collected_by_id` and `collected_at` reflect the input, whose `received_at` is initially absent, whose `rejected_reason` is initially absent, and whose `status` begins at `COLLECTED` (the initial specimen state). The parent order transitions from `ORDERED` to `COLLECTED`. At most one specimen may exist per `LabOrder`; a second specimen-creation request is the concurrency case in §2.12.

A `LabTech` then opens the first transport leg on the specimen by supplying `from_location`, `to_location`, `departed_at`, and `courier_id`. The first leg's `departed_at` must be at or later than the specimen's `collected_at`. The leg is persisted with `specimen_id` set to the parent, `leg_index` set to 1 (the first leg of the chain), `arrived_at` initially absent, and `status` set to `DEPARTED` (the initial leg state). Opening the first leg transitions the specimen from `COLLECTED` to `IN_TRANSIT` and the parent order from `COLLECTED` to `IN_TRANSIT`. Subsequent legs are opened similarly, except that the specimen must already be in `IN_TRANSIT`, the immediately previous leg must already be in `ARRIVED`, and the new leg's `leg_index` must equal one plus the maximum existing `leg_index` for that specimen, with the new leg's `from_location` equal to the previous leg's `to_location`.

A `LabTech` marks a leg arrived by supplying `arrived_at`, which must be at or later than the leg's `departed_at`. The leg transitions from `DEPARTED` to `ARRIVED`; an arrival attempted on an already-arrived leg is the concurrency case in §2.12. When the arriving leg is not the final leg, no further cascade occurs and the specimen and order remain in `IN_TRANSIT`. When the arriving leg's `to_location` equals the lab's location code (the constant `LAB_MAIN`), this is the final leg and the system performs the specimen stability check described below, then either confirms receipt or rejects the specimen.

The specimen stability check computes transit minutes as the difference between the arriving leg's `arrived_at` and the specimen's `collected_at`, expressed in minutes with four fractional digits, and compares the result to the panel's `stability_minutes`. The comparison is strict: transit minutes equal to `stability_minutes` is accepted as on-time, and only transit minutes strictly greater than `stability_minutes` is treated as exceeded. When the check passes, the specimen's `received_at` is set to the leg's `arrived_at`, the specimen transitions from `IN_TRANSIT` to `RECEIVED`, and the parent order transitions from `IN_TRANSIT` to `RECEIVED`. When the check fails, the specimen instead transitions from `IN_TRANSIT` to `REJECTED` with `rejected_reason` set to `STABILITY_EXCEEDED`, the parent order transitions from `IN_TRANSIT` to `REJECTED`, the system auto-issues a `RetestRequest` with `reason` set to `SPECIMEN_REJECTED` and a freshly minted replacement `LabOrder` whose `parent_order_id` is the original order and whose `retest_count` is the original's `retest_count` plus one, and the system appends a `ComplianceAuditEvent` with `event_type` of `SPECIMEN_REJECTED`.

A `LabTech` may also report a broken chain of custody on a `DEPARTED` leg. Reporting the break transitions the leg from `DEPARTED` to `BROKEN`, the specimen from `IN_TRANSIT` to `REJECTED` with `rejected_reason` set to `CHAIN_BROKEN`, and the parent order from `IN_TRANSIT` to `REJECTED`. The system auto-creates a `RetestRequest` whose `reason` is `SPECIMEN_REJECTED` and whose `new_lab_order_id` references a newly minted `LabOrder` that clones the panel and patient with `parent_order_id` set to the original order's id and `retest_count` set to the original's `retest_count` plus one. Two compliance audit events are written, in this order: first an event with `event_type` of `SPECIMEN_REJECTED`, then an event with `event_type` of `RETEST_ISSUED`. Other specimen rejection categories that may appear in `rejected_reason` are `CONTAMINATED` and `INSUFFICIENT_VOLUME`; these are recorded when the cause is determined out-of-band but follow the same downstream cascade.

### 3.4. Producing and Releasing the Result

Once the order is in `RECEIVED` and its specimen is in `RECEIVED`, a clinician may produce the result. The actor submits a `resulted_by_id` and the `measurements` array. Each `measurements` entry carries an `analyte_code`, a numeric `value`, and a `unit`. The submitted set must cover every analyte in the panel exactly once — no analyte missing, no analyte repeated, no analyte not on the panel — and each entry's `unit` must match the panel's declared unit for that analyte. A coverage or unit mismatch is rejected with `ERR_MEASUREMENTS_INCOMPLETE`. The clinician named in `resulted_by_id` must satisfy the CLIA complexity tier of the panel: any active `LAB_TECH` or `LAB_DIRECTOR` may result a `WAIVED` or `MODERATE` panel, but only an active `LAB_DIRECTOR` may result a `HIGH`-complexity panel.

A successful resulting creates a `LabResult` whose `lab_order_id` references the order, whose `resulted_by_id` reflects the input, whose `released_by_id` is initially absent, whose `measurements` are persisted as supplied, and whose `status` is set to `DRAFT` (the initial result state). The `resulted_at` field is set to the server clock at the moment of resulting; `released_at` is initially absent. The system runs the critical-flag computation: for every measurement, it locates the analyte's spec in the panel; if the spec's `critical_low` is present and the measurement's `value` is strictly less than `critical_low`, the system appends a critical-flag entry whose `analyte_code` is the measurement's analyte, whose `side` is `LOW`, whose `value` is the measurement's value, and whose `bound` is `critical_low`; otherwise if the spec's `critical_high` is present and the measurement's `value` is strictly greater than `critical_high`, the system appends an entry with `side` of `HIGH` and `bound` of `critical_high`. A measurement whose value sits at exactly `critical_low` or exactly `critical_high` is not critical because the comparison is strict outside the range. The computed list is stored in `critical_flags`. The system then computes the provisional severity score described in §3.6 and stores it in `severity_score` (default 0 when no flags fire). The parent order transitions from `RECEIVED` to `RESULTED`.

A `LabDirector` releases a `DRAFT` result by supplying a `released_by_id` and optionally a `version`. The clinician named in `released_by_id` must be active, must have `role_kind` of `LAB_DIRECTOR`, and must not be the same clinician as `resulted_by_id` — segregation of duties is the first business-safety check on this endpoint. The result must still be in `DRAFT` and the parent order must still be in `RESULTED`. On release, the result's `status` transitions from `DRAFT` to `RELEASED`, the `released_at` field is set to the server clock, the parent order transitions from `RESULTED` to `RELEASED`, and the system recomputes the severity score using the final variant described in §3.6, replacing the provisional value. When the result's `critical_flags` is empty, the system appends a single `ComplianceAuditEvent` with `event_type` of `RESULT_RELEASED` and the workflow ends with the result released and no notification opened. When the result's `critical_flags` is non-empty, the system additionally creates a `CriticalNotification` whose `lab_result_id` references the result, whose `recipient_clinician_id` is cloned from the order's `ordering_provider_id` at this moment, whose `channel` is set to `SMS` (the initial channel for any new notification), whose `attempt_count` is 0, whose `first_sent_at` is set to the server clock, whose `ack_deadline_at` is computed as described in §3.5, and whose `status` is `PENDING` (the initial notification state). Two audit events are written for this case, in this order: first an event with `event_type` of `RESULT_RELEASED`, then an event with `event_type` of `CRITICAL_NOTIFIED`. The patient's `notification_consent` must permit notification when critical flags are present; a value of `NONE` blocks the release before the notification is created.

A `LabDirector` may amend a `RELEASED` result by supplying new `measurements` (and optionally `version`). The result must be in `RELEASED`. Amendment recomputes `critical_flags` and recomputes the final severity score over the new measurements, replacing the prior value. A `ComplianceAuditEvent` with `event_type` of `AMENDMENT_RECORDED` is appended. When the recomputed `critical_flags` differ from the prior `critical_flags` — whether by introduction of new critical analytes, removal of previous ones, or a change in side — the system auto-creates a `RetestRequest` with `reason` set to `RESULT_AMENDED`, and additionally opens a fresh `CriticalNotification` scoped only to the newly-critical analytes (those flagged by the amendment that were not flagged before), inheriting the same priority-driven deadline rules. The result's `status` transitions from `RELEASED` to `AMENDED`. The parent order remains in `RELEASED` throughout.

A `LabDirector` may retract an `AMENDED` result. The result must currently be in `AMENDED`; retraction transitions its `status` from `AMENDED` to `RETRACTED`. The parent order's `status` is not changed by retraction — it remains in `RELEASED` — but the audit log records the retraction via a `ComplianceAuditEvent` row. An amendment-and-retraction race on a `RELEASED` result is the concurrency case in §2.12.

### 3.5. Critical Notifications, Escalation, and Acknowledgement

A new `CriticalNotification` starts on the `SMS` channel with `PENDING` status, addressed to the recipient cloned from the order's `ordering_provider_id`. Its acknowledgement deadline `ack_deadline_at` is the `first_sent_at` plus a window that depends on the parent order's `priority`: 30 minutes when `priority` is `ROUTINE`, 10 minutes when `priority` is `STAT`.

The `OrderingProvider` named in `recipient_clinician_id` acknowledges the notification by supplying `acknowledged_by_id` and `read_back_text`. The notification's `status` must be `PENDING` or `ESCALATED`; a second acknowledgement after the row has already reached `ACKNOWLEDGED` is rejected with `ERR_ALREADY_ACKNOWLEDGED`, which is distinct from the generic state error. The supplied `acknowledged_by_id` must equal the notification's `recipient_clinician_id` — any other clinician is rejected with `ERR_ACK_BY_WRONG_RECIPIENT`. When the panel's `clia_complexity` is `HIGH`, the `read_back_text` must contain, as a case-insensitive substring, every `analyte_code` present in the result's `critical_flags`; missing any of them is rejected with `ERR_READBACK_INCOMPLETE`. On a successful acknowledgement, the system creates an `AcknowledgementReceipt` whose `critical_notification_id` references the notification, whose `acknowledged_by_id` records the acknowledging clinician, whose `acknowledged_at` is the server clock, whose `read_back_text` is persisted as supplied, and whose `ack_latency_minutes` is computed as the difference between `acknowledged_at` and the notification's `first_sent_at` expressed in minutes to 2 decimal places. The notification transitions to `ACKNOWLEDGED`, and a `ComplianceAuditEvent` with `event_type` of `CRITICAL_ACKED` is appended with the latency embedded in its `payload`.

Escalation and failure are performed by the sweep rather than by a human actor. When the sweep is invoked, it walks every notification whose `status` is in `PENDING` or `ESCALATED`, ordered first by `ack_deadline_at` ascending and then by `created_at` ascending to break ties — this fixed ordering matters because two notifications maturing in the same sweep run must produce deterministic audit-event ordering. For each notification, the sweep behaves as follows. If the server clock is earlier than the notification's `ack_deadline_at`, the notification is skipped. If the notification is `PENDING` on the `SMS` channel and the deadline has elapsed, the sweep transitions it to `ESCALATED`, flips `channel` to `VOICE`, increments `attempt_count` by one (without resetting `first_sent_at`), extends `ack_deadline_at` by 10 minutes regardless of the original priority, and appends a `ComplianceAuditEvent` with `event_type` of `CRITICAL_ESCALATED`. If the notification is `ESCALATED` on the `VOICE` channel and the extended deadline has elapsed, the sweep transitions it to `FAILED`, increments `attempt_count` by one, auto-creates a `RetestRequest` with `reason` set to `CRITICAL_UNACKNOWLEDGED` whose `new_lab_order_id` references a freshly minted replacement `LabOrder` cloning patient and panel with `parent_order_id` set to the original order and `retest_count` incremented, and appends a `ComplianceAuditEvent` with `event_type` of `CRITICAL_ESCALATED` whose `payload` carries a failure flag. Notifications may be listed with optional `status` and `recipient_clinician_id` filters alongside the standard `limit` and `offset`.

### 3.6. Severity Scoring: Provisional and Final

The system computes two structurally distinct severity scores on the same set of critical flags, and the variant used depends on the result's lifecycle stage. Both variants use a per-flag weight of 2 when the flag's `side` is `HIGH` and 1 when the flag's `side` is `LOW`, and both compute a per-analyte distance as the absolute difference between the flag's `value` and the flag's `bound`, divided by the maximum of the absolute value of the `bound` and 1.

The **provisional** variant is computed on resulting (when the result enters `DRAFT`) and considers only the critical flags of this single result, with no patient history. The system accumulates, across every entry in `critical_flags`, the product of the flag's weight and the flag's per-analyte distance into a running raw total. After the loop completes, the raw total is rounded once at the very end to 2 decimal places using round-half-up. This is the sum-then-round ordering.

The **final** variant is computed on release (when the result enters `RELEASED`) and on amendment (when the result enters `AMENDED`), and replaces the provisional value. It blends in patient history alongside the current result's flags: the system looks up the two most recently released lab results for the same `patient_id` and the same `panel_id`, ordered by `released_at` descending, excluding the current result itself. From that lookback of up to two prior results, the system counts how many had any critical flags, multiplies that count by 0.25, adds 1.0, and uses the sum as a historical factor. Then, for every entry in `critical_flags`, the system computes the product of the flag's weight, the flag's per-analyte distance, and the historical factor; each such per-flag product is independently rounded to 2 decimal places using round-half-up to form a per-flag piece. The final score is the plain sum of these pieces with no further rounding applied. This is the round-then-sum ordering, with a different input set than the provisional. Because the two variants differ in both inclusion set and rounding order, the same `critical_flags` ordinarily produce different scores under the two variants — this is by design, not by error.

### 3.7. Retests

A `RetestRequest` is the system's mechanism for surfacing the need to redraw and re-run an order. Three causes auto-issue a retest, recorded in `reason`: `SPECIMEN_REJECTED` (the specimen was rejected at receipt for stability or at any time for a broken chain), `CRITICAL_UNACKNOWLEDGED` (the notification reached `FAILED` after sweep escalation), and `RESULT_AMENDED` (an amendment changed the set of critical analytes). Every auto-issued retest begins with `status` set to `ISSUED` (the initial retest state) and a `new_lab_order_id` reference to a replacement `LabOrder` whose `parent_order_id` is set to the original and whose `retest_count` is incremented.

A retest reaches `FULFILLED` automatically when the spawned replacement order itself reaches `RELEASED`; this is a system-driven transition with no human actor. Before that happens, an `OrderingProvider` may cancel an `ISSUED` retest provided the actor's id equals the original order's `ordering_provider_id` and the replacement order is either absent or still in `ORDERED`; the retest's `status` transitions to `CANCELED`, and when the replacement order is present and still in `ORDERED`, that replacement order is itself transitioned to `CANCELED` as part of the same operation. Retests may be listed with optional `status` and `lab_order_id` filters.

### 3.8. Compliance Audit Trail and Test-Driving Capabilities

The compliance audit trail is the durable record of every clinically significant event. Each `ComplianceAuditEvent` row carries an `event_type` drawn from `ORDER_PLACED`, `SPECIMEN_REJECTED`, `RESULT_RELEASED`, `CRITICAL_NOTIFIED`, `CRITICAL_ACKED`, `CRITICAL_ESCALATED`, `RETEST_ISSUED`, or `AMENDMENT_RECORDED`; a `lab_order_id` that is always set to the order at the root of the activity; an `actor_id` that is a `Clinician.id` when the event was triggered by a human action and the literal string `"system"` when triggered by the sweep; and a `payload` carrying an event-specific JSON snapshot (for example, critical analyte codes on a notification event, or `ack_latency_minutes` on an acknowledgement event). A `LabDirector` may list audit events with optional `lab_order_id` and `event_type` filters.

Two test-driving capabilities exist for laboratory operations and integration testing. A clock-advance capability lets a `LabDirector` move the server's notion of "now" forward by supplying a `to_iso8601` instant; subsequent calls to read the server clock or to run the sweep observe the new time. A clock-read capability is available to all three roles and reports the server's current clock. The sweep itself is a `LabDirector` capability that performs the escalation and failure walk described in §3.5; it takes no body.

## 4. Endpoint Definitions

Operations that create a brand-new resource — a patient, a clinician, a panel, a lab order, a specimen, a transport leg, or a result — return `201 Created`. Operations that modify an existing resource — cancellation, arrival, break-reporting, release, amendment, retraction, acknowledgement, retest cancellation, clock advance, and sweep — return `200 OK`. Read endpoints return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST   | `/patients`                                 | Create a patient                                                          | OrderingProvider, LabDirector |
| GET    | `/patients`                                 | List patients (filter by `mrn` substring, paginate)                       | OrderingProvider, LabTech, LabDirector |
| GET    | `/patients/{id}`                            | Fetch a patient                                                           | OrderingProvider, LabTech, LabDirector |
| POST   | `/clinicians`                               | Register a clinician                                                      | LabDirector |
| PATCH  | `/clinicians/{id}`                          | Update clinician `active` flag or `phone_e164`; supports `version`         | LabDirector |
| GET    | `/clinicians/{id}`                          | Fetch a clinician                                                         | OrderingProvider, LabTech, LabDirector |
| POST   | `/test-panels`                              | Create a CLIA panel definition                                            | LabDirector |
| GET    | `/test-panels/{id}`                         | Fetch a panel                                                             | OrderingProvider, LabTech, LabDirector |
| POST   | `/lab-orders`                               | Place a lab order                                                         | OrderingProvider |
| GET    | `/lab-orders`                               | List lab orders (filter by `status`, `patient_id`, `panel_id`; paginate)   | OrderingProvider, LabTech, LabDirector |
| GET    | `/lab-orders/{id}`                          | Fetch a lab order                                                         | OrderingProvider, LabTech, LabDirector |
| POST   | `/lab-orders/{id}/cancel`                   | Cancel an `ORDERED` lab order                                             | OrderingProvider |
| POST   | `/lab-orders/{id}/specimens`                | Record specimen collection                                                | LabTech |
| POST   | `/lab-orders/{id}/results`                  | Produce a draft result for the order                                      | LabTech, LabDirector |
| GET    | `/specimens/{id}`                           | Fetch a specimen                                                          | OrderingProvider, LabTech, LabDirector |
| POST   | `/specimens/{id}/transport-legs`            | Open a new transport leg                                                  | LabTech |
| GET    | `/specimens/{id}/transport-legs`            | List transport legs of a specimen in `leg_index` order                    | OrderingProvider, LabTech, LabDirector |
| POST   | `/transport-legs/{id}/arrive`               | Mark leg arrival; final leg may flip specimen and order                   | LabTech |
| POST   | `/transport-legs/{id}/report-break`         | Report a broken chain of custody for an open leg                          | LabTech |
| GET    | `/results/{id}`                             | Fetch a lab result                                                        | OrderingProvider, LabTech, LabDirector |
| POST   | `/results/{id}/release`                     | Release a `DRAFT` result                                                   | LabDirector |
| POST   | `/results/{id}/amend`                       | Amend a `RELEASED` result                                                 | LabDirector |
| POST   | `/results/{id}/retract`                     | Retract an `AMENDED` result                                               | LabDirector |
| GET    | `/notifications/{id}`                       | Fetch a critical notification                                             | OrderingProvider, LabDirector |
| GET    | `/notifications`                            | List notifications (filter by `status`, `recipient_clinician_id`)          | OrderingProvider, LabDirector |
| POST   | `/notifications/{id}/acknowledge`           | Acknowledge a critical notification with read-back                        | OrderingProvider |
| GET    | `/retest-requests/{id}`                     | Fetch a retest request                                                    | OrderingProvider, LabTech, LabDirector |
| GET    | `/retest-requests`                          | List retest requests (filter by `status`, `lab_order_id`)                  | OrderingProvider, LabTech, LabDirector |
| POST   | `/retest-requests/{id}/cancel`              | Cancel an issued retest                                                   | OrderingProvider |
| GET    | `/audit-events`                             | List CLIA audit events (filter by `lab_order_id`, `event_type`)            | LabDirector |
| POST   | `/_clock/advance`                           | Advance the system clock to a supplied `to_iso8601` instant               | LabDirector |
| GET    | `/_clock`                                   | Fetch the current system clock                                            | OrderingProvider, LabTech, LabDirector |
| POST   | `/_sweep/run`                               | Run the notification sweep (escalation and failure)                       | LabDirector |

## 5. Error Code Catalogue

| Error ID                            | HTTP Status Code |
| ----------------------------------- | ---------------- |
| `ERR_AUTH_REQUIRED`                 | 401 Unauthorized |
| `ERR_FORBIDDEN`                     | 403 Forbidden    |
| `ERR_NOT_FOUND`                     | 404 Not Found    |
| `ERR_INVALID_STATE`                 | 409 Conflict     |
| `ERR_VERSION_CONFLICT`              | 409 Conflict     |
| `ERR_CLIA_SOD_VIOLATION`            | 422 Unprocessable Entity |
| `ERR_CLIA_COMPLEXITY_VIOLATION`     | 422 Unprocessable Entity |
| `ERR_PATIENT_CONSENT_BLOCKED`       | 422 Unprocessable Entity |
| `ERR_ACK_BY_WRONG_RECIPIENT`        | 422 Unprocessable Entity |
| `ERR_READBACK_INCOMPLETE`           | 422 Unprocessable Entity |
| `ERR_TIME_ORDER_INVALID`            | 422 Unprocessable Entity |
| `ERR_TRANSPORT_CHAIN_BROKEN`        | 422 Unprocessable Entity |
| `ERR_MEASUREMENTS_INCOMPLETE`       | 422 Unprocessable Entity |
| `ERR_CLINICIAN_INACTIVE`            | 422 Unprocessable Entity |
| `ERR_ALREADY_ACKNOWLEDGED`          | 409 Conflict     |
| `ERR_LEG_ALREADY_ARRIVED`           | 409 Conflict     |
| `ERR_SPECIMEN_ALREADY_EXISTS`       | 409 Conflict     |
| `ERR_INVALID_PAGINATION`            | 400 Bad Request  |
| `ERR_VALIDATION`                    | 422 Unprocessable Entity |
