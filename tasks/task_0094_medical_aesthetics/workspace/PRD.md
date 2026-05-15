# Medical Aesthetics API — Product Requirements Document

## 1. Introduction

Medical aesthetics is a regulated clinical practice where surgical, non-surgical, and skincare procedures are delivered against tight safety constraints, multi-party approval chains, and traceable consumable usage. Institutions running these programs must keep a curated catalog of procedures, qualify physicians and rooms for each, manage customer contraindications, capture informed consent, and produce auditable operative records — while at the same time scheduling rooms, doctors, nurses, anesthesia, and equipment without conflict and reconciling installment-finance arrangements with consumer-finance partners.

This document specifies the API that powers such an institution. The system is organized around seven workflows that interlock: project catalog onboarding and on-shelf review; customer profile and contraindication management; treatment-plan design with multi-physician approval; four-way appointment scheduling with anesthesia allocation; intra-operative records with lot-number traceability; staged post-operative follow-up with adverse-event detection; and installment financing with KYC, default handling, and refund-on-medical-event rules. Cross-cutting concerns — audit logging, version-pinning of approved plans, event emission to downstream payment, finance-partner, IM and pharmaceutical-traceability systems, and scheduled time-driven sweeps — bind these workflows together.

The product audience is the engineering team building the back-end service mounted under `/aesthetics`. The contract here is closed-form: every state, transition, calculation, and validation rule is enumerated, and the implementation must adhere strictly to the precise mechanics described.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID` and `X-User-Role`. A request missing either header, or carrying a `X-User-Role` value the system does not recognize, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request with both headers present but whose role is not permitted to invoke the target endpoint per the RBAC matrix in §4 is rejected with `ERR_FORBIDDEN` (HTTP 403).

The recognized roles, spelled exactly as required, are: `MedicalDirector`, `Consultant`, `AttendingPhysician`, `SeniorPhysician`, `Nurse`, `FinanceOfficer`, and `Customer`.

Of these roles, only `Customer` is entity-backed. When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting `Customer`; ownership checks on any resource that references a `Customer` compare the resource's foreign-key field (for example, `TreatmentPlan.customer_id` or the `customer_id` derivable from a `FollowUp.appointment_id`'s parent appointment's plan) to `X-User-ID`. When `X-User-Role` is any of `MedicalDirector`, `Consultant`, `AttendingPhysician`, `SeniorPhysician`, `Nurse`, or `FinanceOfficer`, `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity row. The server may record it (for example, as `reviewer_id` on `Project` when a medical-director approval transition writes it, as `consultant_id` on `TreatmentPlan` when a plan is created, as `senior_physician_id` on `TreatmentPlan` when countersign fires, or on every `AuditEntry.actor_id`) but does not look it up in any entity's primary-key index. For physician roles the opaque id is the qualifying doctor id and must match `Project.qualified_doctor_ids` and `TreatmentPlan.attending_physician_id` when ownership is required by a transition's preconditions.

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

Every list endpoint accepts two query parameters: `limit` and `offset`. The `limit` defaults to 10, has a minimum of 1, and a maximum of 100; `offset` defaults to 0 and has a minimum of 0. Any request that supplies a `limit` outside the 1-to-100 range, or an `offset` below 0, is rejected with `ERR_PAGINATION_OUT_OF_RANGE` (HTTP 400). The fields `limit`, `offset`, `total_count`, and `has_more` are included in the `meta` envelope of every list response. List results are sorted by `created_at` ascending unless an endpoint description in §4 says otherwise.

### 2.4. Common Resource Properties, Versioning, and OCC

Every persisted entity is identified by an `id` that is a server-minted UUID string with no type prefix. Most entities also carry an entity-level `version` integer (which starts at 1 on creation and increments by exactly 1 on every successful mutation), a `created_at` ISO 8601 UTC timestamp with three fractional digits set at creation time, and an `updated_at` timestamp with the same format refreshed on every mutation. The entities that participate in this common-fields contract are `Project`, `ConsumableSku`, `Customer`, `ContraindicationRule`, `TreatmentPlan`, `Appointment`, `Room`, `FollowUp`, `AdverseEvent`, and `InstallmentPlan`.

Three entities deviate from this convention because they are append-only logs or join records: `OperativeRecord`, `PaymentEvent`, `AuditEntry`, and `SyncEvent` carry only `id` and `created_at` — both `updated_at` and `version` are absent on these records and must not be present in their JSON output.

Optimistic concurrency control runs on the entity-level `version` field. Any mutating endpoint that accepts a request body documents `version` as optional. When the client supplies `version`, the server compares it to the current persisted version: if they match, the mutation proceeds and `version` is incremented; if they differ, the mutation is rejected with `ERR_VERSION_CONFLICT` (HTTP 409). When the client omits `version` from the body, the OCC check is skipped and the mutation proceeds against whatever the current value is. OCC takes priority over downstream business rules: a stale-version submission surfaces `ERR_VERSION_CONFLICT` rather than being masked by a later business check, so the client can retry against fresh data.

`TreatmentPlan` additionally maintains a separate semantic counter named `plan_version` (distinct from the OCC `version`). The semantic `plan_version` starts at 1 when a plan is created and is incremented by 1 every time a DRAFT plan is edited via the consultant-edit transition. The OCC `version` is incremented on every mutation regardless of state; `plan_version` is incremented only on the DRAFT-edit transition.

### 2.5. Hierarchical Path Resolution

Nested resource paths are resolved left-to-right. For any path containing more than one resource identifier, the server resolves each identifier in path order, and the first one that does not exist or fails an ownership check causes the request to be rejected with `ERR_NOT_FOUND` (HTTP 404). Foreign-key references inside request bodies are also validated for existence at the time the body is processed; an unknown foreign key produces `ERR_NOT_FOUND` as well. Schema/type validation of the request body (required keys present, types correct) precedes business rules; a malformed body yields `ERR_INVALID_INPUT` (HTTP 400).

### 2.6. Validation Order and Precedence

When more than one validation can apply to a single endpoint, the system evaluates them in a fixed priority order so that the surfaced error is deterministic. The order is: authentication (`ERR_UNAUTHENTICATED`) first, then authorization (`ERR_FORBIDDEN`), then path-existence (`ERR_NOT_FOUND` on path-bearing resources), then body foreign-key existence (also `ERR_NOT_FOUND`), then state preconditions (`ERR_INVALID_STATE`), then OCC version match (`ERR_VERSION_CONFLICT`). After these gates clear, business-safety checks run — customer age at submission, absolute-contraindication, segregation-of-duties for countersign, lot-number requirement, consent-signed-before-approval — followed by business-referential checks (doctor-qualified, project-on-shelf, anesthesia requirement vs project category, room kind vs project category), then business-temporal checks (doctor / nurse / room / equipment / anesthesia overlap, check-in window), then business-constraint checks (reschedule limit, plan items length, plan stale-reference, pagination range, schema). Within each category the priorities ordered higher in the list above fire first; in particular, the `ERR_INVALID_STATE` gate precedes `ERR_VERSION_CONFLICT`, which itself precedes every business check. Pagination-range and request-schema checks belong to the business-constraint group and are evaluated after auth, existence, and state gates.

### 2.7. State and Side-Effect Consistency

Every successful state transition or mutation refreshes the affected entity's `updated_at` and increments its `version`. When a transition has cascade effects on a child or peer entity, the child's `updated_at` and `version` are refreshed independently in the same operation. Where a parent transition snapshots data from a referenced resource (notably the `locked_project_versions` map captured at plan approval), subsequent changes on the referenced resource are detected by comparing its live `version` to the snapshot; mismatch is reported as `ERR_PLAN_STALE_REFERENCE` on operations that consume the snapshot.

### 2.8. Precision, Rounding, and Numeric Conventions

All monetary fields are stored as integer cents. Calculations that materially round (the per-line discount in `plan_total_final`, the monthly-payment derivation in `installment_schedule`, the customer-risk score) are explicit about the rounding step they take. Where the scaffold prescribes "round half up", the system rounds half away from zero. The `customer_risk_score` is held to one decimal place; the installment schedule produces integer cents per period with the final period absorbing any rounding residual so that the sum of per-period principal equals the original principal exactly.

### 2.9. Audit Logging and Outbound Event Emission

Every approval-, rejection-, cancellation-, state-transition-, and operative-record action is captured as an `AuditEntry` row with `actor_role`, `actor_id`, `action`, `subject_type`, `subject_id`, and an action-specific `payload` snapshot. The `actor_role` mirrors the `X-User-Role` of the originating request; the `actor_id` mirrors `X-User-ID`. Audit entries are written synchronously inside the transition's transaction; they are not refreshable and carry no entity `version`.

The system also emits `SyncEvent` records (a read-only outbox) on selected transitions, with a `topic`, an event `kind` string, a `payload`, and an `emitted_at` server timestamp. Recognized topics are `PAYMENT`, `FINANCE_PARTNER`, `IM`, and `PHARMA_TRACE`; recognized kinds include but are not limited to `PLAN_APPROVED`, `INSTALLMENT_PAID`, `CONSUMABLE_USED`, `FOLLOWUP_REMINDER`, `PLAN_ACTIVATED`, `DEFAULT_STRIKE`, `PLAN_SETTLED`, and `REFUND_INITIATED`. The outbox is queryable for inspection.

### 2.10. Time-Driven Sweeps and the Test Clock

A privileged endpoint exposes a logical clock advancement — invoking it with a `seconds` payload moves the server's wall-clock perception forward by that many seconds and triggers three sweeps in sequence: appointments still `SCHEDULED` past their `scheduled_end` plus 60 minutes transition to `NO_SHOW`; follow-ups still `PENDING` past their `due_at` plus 7 days transition to `MISSED`; installment plans in `ACTIVE` with any schedule entry past its `due_date` plus the seven-day grace transition to `IN_DEFAULT` with a strike incremented and a collection-notice event recorded. This capability is reserved for `MedicalDirector`.

## 3. Business Logic & Workflows

### 3.1. Project Catalog Onboarding and Review

The project catalog is the institution's authoritative source for what may be planned, priced, scheduled, and consented to. Each `Project` is created by either a `MedicalDirector` or a `Consultant` in `DRAFT` status with a short unique `code` (3 to 32 characters, unique across all projects), a display `name`, a `category` chosen from `SURGICAL`, `NON_SURGICAL`, or `SKINCARE`, a free-text `technique` narrative, a planned `duration_minutes` between 5 and 480 minutes inclusive, an expected `recovery_days` between 0 and 365 inclusive, a `risk_level` of `LOW`, `MEDIUM`, or `HIGH`, a non-empty bill of materials in the `bom` field consisting of `{sku_id, quantity}` objects with each `quantity` strictly greater than 0, a non-empty `qualified_doctor_ids` array enumerating doctor user-ids permitted as attending physician for the project, and at least one entry in `pricing_tiers`. Each pricing tier carries a `tier_code` unique within the project, a non-negative `base_price_cents`, and a `min_quantity` of at least 1; the tier array is sorted ascending by `min_quantity` at create time.

Upon creation the project's `status` is `DRAFT`. A submission action by `Consultant` or `MedicalDirector` transitions the project to `UNDER_REVIEW` provided `bom`, `qualified_doctor_ids`, and `pricing_tiers` are each non-empty. From `UNDER_REVIEW` a `MedicalDirector` may take one of two actions: an approval which advances the project to `ON_SHELF` and writes the acting user's id into `reviewer_id`, or a rejection which sends the project back to `DRAFT`. Once on shelf, a `MedicalDirector` may take the project off shelf — `ON_SHELF` to `OFF_SHELF` — but only when no `TreatmentPlan` in `DRAFT` or `SUBMITTED` status references the project; approved plans are allowed to outlive an off-shelf action because they hold a locked snapshot of the project. Attempting to take an off-shelf action when non-terminal plans still reference the project is rejected with `ERR_PROJECT_IN_USE` (HTTP 409). A project that is currently off shelf may be returned to shelf again by a `MedicalDirector`, with the transition `OFF_SHELF` to `ON_SHELF`. Every project state transition writes an audit entry with an action of `PROJECT_SUBMITTED`, `PROJECT_APPROVED`, `PROJECT_REJECTED`, `PROJECT_OFF_SHELF`, or `PROJECT_RETURNED` as appropriate.

Editing a project is permitted while the project is in either `DRAFT` or `UNDER_REVIEW` and increments the project's OCC `version`. The editable fields are `name`, `technique`, `duration_minutes`, `recovery_days`, `risk_level`, `bom`, `qualified_doctor_ids`, and `pricing_tiers`. A `HIGH` `risk_level` is significant beyond the catalog itself: any treatment plan that includes a project with `risk_level` equal to `HIGH` triggers a senior-physician countersign requirement, expressed below.

A simultaneous take-off-shelf and submit-plan-referencing-that-project arrive at the system as racing operations; the system serializes them on `Project.status` so that exactly one wins. If take-off-shelf wins first, the racing submit fails with `ERR_PROJECT_NOT_ON_SHELF` (HTTP 422) because at the moment of submit evaluation the project is no longer `ON_SHELF`. If submit wins first, the racing take-off-shelf fails with `ERR_PROJECT_IN_USE` (HTTP 409) because a `SUBMITTED` plan still references the project.

`ContraindicationRule` records are attached one-by-one to a project by a `MedicalDirector` and are read by physicians, consultants, and senior physicians. Each rule carries the parent's `project_id`, a `severity` of `ABSOLUTE` or `RELATIVE`, a `predicate` object of shape `{ field, op, value }` whose `field` is a dotted path on `Customer` (for example, `health_declaration.is_pregnant`), whose `op` is one of `EQ`, `IN`, `GT`, or `LT`, and whose `value` is the literal to compare against, plus a human-readable `reason` logged whenever the rule triggers. An `ABSOLUTE` rule blocks plan submission outright; a `RELATIVE` rule does not block but forces senior countersign on the resulting plan.

`ConsumableSku` records are registered by a `MedicalDirector`. Each SKU carries a globally unique `sku_code` matching the regular-expression form of three to thirty-two characters drawn from uppercase letters, digits, and hyphens, a display `name`, a `kind` of `CONSUMABLE` or `DRUG`, and a `requires_lot_tracking` boolean which defaults to true and dictates whether usage of this SKU must capture a lot number.

`Room` records are registered by a `MedicalDirector` with a unique `code`, a `room_kind` of `SURGICAL_OR`, `PROCEDURE`, or `TREATMENT`, and an `is_active` boolean which defaults to true. A room with `is_active` false cannot be booked. The `room_kind` of `SURGICAL_OR` is required when (and only when) the project's `category` is `SURGICAL`; this is enforced when the appointment is created or rescheduled and surfaces as `ERR_ROOM_KIND_MISMATCH` (HTTP 422).

### 3.2. Customer Profile, Contraindications, and Risk Score

A `Consultant` creates a `Customer` row with the customer's `full_name`, an ISO 8601 `date_of_birth`, a primary `contact_phone` in E.164 form, and optional declarative arrays `medical_history`, `allergies`, and `medication_history` (each defaulting to an empty array), a `health_declaration` object — which when present must include the boolean keys `is_pregnant`, `has_uncontrolled_hypertension`, `has_active_infection`, and `has_bleeding_disorder` — and optional asset-id arrays `photo_archive_ids` and `scan3d_archive_ids` referencing stored photos and three-dimensional scans (each defaulting to an empty array).

Three computed fields on the customer are seeded at creation and recomputed on subsequent edits. The `kyc_status` defaults to `NOT_VERIFIED` and can take the values `NOT_VERIFIED`, `PENDING`, `VERIFIED`, or `REJECTED`; the `credit_score` is an integer between 0 and 1000 inclusive, snapshotted when KYC is verified, and defaults to null until then. The `adverse_event_count` defaults to 0 and counts the customer's confirmed adverse events. The `risk_score` is a number with one decimal place, defaulting to 0 at creation, recomputed whenever the customer's declarative fields (`health_declaration`, `allergies`, `medical_history`) change and whenever an adverse event is filed or escalated against the customer's procedures.

The risk-score calculation begins from a base of 0. Pregnancy adds 30 to the base; uncontrolled hypertension adds 25; active infection adds 20; bleeding disorder adds 25. Each entry in `allergies` adds 5 to the base, and each entry in `medication_history` adds 3. After the base is accumulated, an adverse-event multiplier is applied: the multiplier equals 1.0 plus 0.25 multiplied by the customer's `adverse_event_count`. The raw score is the product of the base and this multiplier. The final `risk_score` is the raw score rounded half-up to one decimal, then clamped so that values below 0 are reported as 0.0 and values above 100 are reported as 100.0. Two variants of this computation exist: when `adverse_event_count` is exactly 0 the multiplier is 1.0 and the score depends purely on the declarative fields; when `adverse_event_count` is at least 1 the multiplier amplifies the same declarative inputs to a different final score, so identical declarative inputs on two customers can yield two different scores. A customer whose live `risk_score` is at least 80 has their future plans flagged for senior countersign at submission time.

KYC and credit are advanced by a `FinanceOfficer` through a dedicated KYC endpoint that accepts `kyc_status` and `credit_score` and writes both into the customer's record, leaving an audit entry behind. A customer may update their own declarative profile (sharing this capability with the `Consultant`), with the request body accepting optional `full_name`, `contact_phone`, `medical_history`, `allergies`, `medication_history`, `health_declaration`, `photo_archive_ids`, `scan3d_archive_ids`, and `version`. Each such edit triggers a risk-score recomputation.

### 3.3. Plan Design, Submission, Consent, and Approval

A `Consultant` opens a treatment plan in `DRAFT` status, supplying the owning `customer_id`, an `items` array of `{project_id, tier_code, quantity}` entries of length 1 to 10, an `expected_outcome` narrative shared with the customer, a `risk_disclosure` document text, and optionally an `attending_physician_id` chosen at proposal time. The plan also records the originating consultant's id in `consultant_id`. Within `items`, every `project_id` must point to a project whose `status` is `ON_SHELF` at the moment the plan is submitted, the `tier_code` must exist in that project's `pricing_tiers`, and the `quantity` is a positive integer, defaulting to 1 when omitted from input. A plan whose `items` length falls outside 1 to 10 — either empty or with eleven or more entries — is rejected at create or edit time with `ERR_PLAN_ITEMS_OUT_OF_RANGE` (HTTP 422). When the chosen `attending_physician_id` is not present in `Project.qualified_doctor_ids` for every included project the request is rejected with `ERR_DOCTOR_NOT_QUALIFIED` (HTTP 422); this check fires at plan creation, plan submission, and appointment creation.

Two computed totals live on the plan. `provisional_total_cents` is written at create time, recomputed on every DRAFT edit, and recomputed again at submission. It iterates `items` in order; for each item it fetches the live project, locates the matching pricing tier by `tier_code`, multiplies `base_price_cents` by `quantity` to form a line total, and accumulates the line total into a running sum. Per-line rounding is applied in this order — multiply-then-accumulate — though for pure integer cents the per-line rounding step has no effect. The provisional variant reads pricing live, so the same plan's `provisional_total_cents` may drift across edits if the underlying project pricing is changed by the catalog. No promotional discount is applied to the provisional total.

The plan's `requires_senior_countersign` flag is computed whenever the plan is created, edited, or submitted. It is true when any included project's `risk_level` is `HIGH`, or when any `ContraindicationRule` of severity `RELATIVE` evaluates true against the customer, or when the customer's current `risk_score` is at least 80. Otherwise it is false.

Editing a `DRAFT` plan is reserved to the consultant who created it (the acting `X-User-ID` must equal the plan's `consultant_id`); the consultant-edit transition accepts optional `items`, `expected_outcome`, `risk_disclosure`, `attending_physician_id`, and `version`, increments the semantic `plan_version` by 1 in addition to the OCC `version`, recomputes `provisional_total_cents`, and recomputes `requires_senior_countersign`. Submission moves the plan from `DRAFT` to `SUBMITTED`. At submission time the system rechecks that each item's project is `ON_SHELF` (`ERR_PROJECT_NOT_ON_SHELF` otherwise, HTTP 422), that the attending physician remains qualified for every project (`ERR_DOCTOR_NOT_QUALIFIED`), that no `ABSOLUTE` contraindication rule evaluates true (`ERR_ABSOLUTE_CONTRAINDICATION`, HTTP 422), and that the customer's age at submission time is at least 18 (`ERR_CUSTOMER_UNDERAGE`, HTTP 422). The customer's age is derived from `date_of_birth` and the server's current time at the moment of evaluation. Submission recomputes `requires_senior_countersign`, recomputes `provisional_total_cents`, and writes an audit entry with action `PLAN_SUBMITTED`.

While the plan is `SUBMITTED`, the `Customer` who owns it signs the informed-consent record through a sign-consent action. This is a self-loop on the `SUBMITTED` status that requires the acting customer to equal `TreatmentPlan.customer_id` and requires `informed_consent_signed_at` to currently be null; it sets `informed_consent_signed_at` to the server's current time and writes an audit entry with action `CONSENT_SIGNED`. The plan cannot advance to `APPROVED` until `informed_consent_signed_at` is non-null; an attempt to approve or countersign before consent is rejected with `ERR_CONSENT_NOT_SIGNED` (HTTP 422).

Two distinct transitions move the plan from `SUBMITTED` to `APPROVED`. The first is approval by the attending physician, available only when `requires_senior_countersign` is false: the acting physician's `X-User-ID` must equal `attending_physician_id`, `informed_consent_signed_at` must be non-null, and on success the plan's `status` becomes `APPROVED`, `final_total_cents` is computed and locked, `locked_project_versions` is snapshotted, an audit entry with action `PLAN_APPROVED` is written, and a `SyncEvent` with topic `IM` and kind `PLAN_APPROVED` is emitted. The second is countersign by a senior physician, used when `requires_senior_countersign` is true: the same consent and physician-equality requirements apply, plus the acting `SeniorPhysician` must not be the same id as `attending_physician_id` (segregation of duties; otherwise the request is rejected with `ERR_SEGREGATION_VIOLATION`, HTTP 422). On success the plan's `status` is set to `APPROVED`, `senior_physician_id` is set to the acting user, `final_total_cents` is computed and locked, `locked_project_versions` is snapshotted, an audit entry with action `PLAN_COUNTERSIGNED` is written, and a `SyncEvent` with topic `IM` and kind `PLAN_APPROVED` is emitted. In both paths the snapshot map `locked_project_versions` is of the shape `{project_id: Project.version}` over every included project, capturing the project rows' current OCC versions at the moment of approval.

The `final_total_cents` calculation differs from the provisional in three concrete ways: it locks pricing to the snapshot taken at approval time (rather than reading live), it applies a promotional discount if the plan has at least 3 items, and its rounding order is per-line discount first then sum (no final rounding step over the sum). For each item, the line gross is `base_price_cents` (from the snapshot tier) multiplied by `quantity`. The promotional rate in basis points is 500 when the number of items in the plan is at least 3 and 0 otherwise. The line discount is the line gross multiplied by the promotional rate and then divided by 10000 using integer floor division; this floor step is the locked rounding semantics. The line net is the line gross minus the line discount; per-line rounding then leaves the integer cents unchanged. The line nets are accumulated into `final_total_cents`. Because the snapshot pricing may differ from the live pricing read at submission, and because the promotion only applies at finalization, the provisional and final totals can diverge for the same item list.

Two further mid-`SUBMITTED` transitions exist. A rejection by the attending physician moves the plan from `SUBMITTED` to the terminal `REJECTED` status with an audit entry of action `PLAN_REJECTED`. A return-to-draft by the originating consultant moves the plan from `SUBMITTED` back to `DRAFT`, clears `informed_consent_signed_at` (so consent must be re-collected the next time), and writes an audit entry with action `PLAN_RETURNED_TO_DRAFT`. From `APPROVED`, the attending physician may cancel the plan to the terminal `CANCELLED` status; cancellation is permitted only when no appointment of this plan is currently `IN_PROGRESS` or `COMPLETED`. Cancellation cascades to every appointment of the plan still in `SCHEDULED` or `CHECKED_IN`, transitioning each to `CANCELLED`. If an `InstallmentPlan` exists for the plan in `ACTIVE` status, the cancellation cascade transitions it to `REFUNDED`, writes a `PaymentEvent` of kind `REFUND` for the current `paid_amount_cents`, and emits a `SyncEvent` with topic `FINANCE_PARTNER` and kind `REFUND_INITIATED`. The cascade has depth 3: plan cancel triggers installment refund triggers finance-partner emission. An audit entry of action `PLAN_CANCELLED` is written. Throughout the plan's lifecycle, list endpoints filter on `customer_id` and `status`.

Concurrent operations on the same plan are serialized so that exactly one wins. Two consultant edits or submits racing on the same `DRAFT` plan are serialized on the plan's OCC `version`: the second writer sees `ERR_VERSION_CONFLICT` (HTTP 409). An approve and a return-to-draft firing simultaneously on the same `SUBMITTED` plan are serialized on `status`: whichever lands first wins, and the loser sees `ERR_INVALID_STATE` (HTTP 409) because at evaluation time the plan is no longer in the state its transition required.

### 3.4. Appointment Scheduling and Four-Way Resource Matching

Once a plan is `APPROVED`, the consultant creates one `Appointment` per item to be performed. The request body carries the parent `plan_id`, the `project_id` identifying which plan item this appointment fulfills, a `scheduled_start` ISO 8601 UTC timestamp, the `doctor_id` (which must equal the plan's attending physician at appointment-create time and must remain in the project's `qualified_doctor_ids`), a `nurse_id`, a `room_id`, a non-empty `equipment_ids` array, and an optional `anesthesia_resource_id`. Two computed temporal fields are derived: `scheduled_end` equals `scheduled_start` plus the project's `duration_minutes`, and `prep_window_start` equals `scheduled_start` minus the project-specific prep-lead time described below. The appointment's `status` defaults to `SCHEDULED`, and a `reschedule_count` defaults to 0 with a hard cap of 3.

The prep-lead time is computed by aggregating per-SKU prep durations across the project's `bom`. Each `ConsumableSku` contributes a per-unit prep-minutes constant: drugs contribute 4 minutes per unit and consumables 2 minutes per unit. For every BOM entry the system multiplies the `quantity` by that per-unit constant to produce a raw figure, then rounds that raw figure up to the next whole multiple of 5 minutes — this per-SKU ceiling is taken first. Then the maximum across all per-SKU ceilings is taken; the alternatives of summing before ceiling, or taking the max of the raw values before ceiling, are explicitly not used. If the project's `category` is `SURGICAL`, a fixed surgical pad of 30 minutes is added to the maximum. The resulting integer-minute value is `prep_lead_minutes`, used to derive `prep_window_start`. The rounding order is therefore: per-SKU ceil-to-multiple-of-5 first, then max across SKUs, then plus 30 if surgical.

The anesthesia field is required if and only if the project's `category` is `SURGICAL`. Supplying `anesthesia_resource_id` for a non-surgical project, or omitting it for a surgical project, yields `ERR_ANESTHESIA_REQUIREMENT_MISMATCH` (HTTP 422). The room's `room_kind` must be `SURGICAL_OR` if and only if the project's `category` is `SURGICAL`; mismatch yields `ERR_ROOM_KIND_MISMATCH` (HTTP 422). The four-way resource match is then performed against existing appointments whose `status` is in `SCHEDULED`, `CHECKED_IN`, or `IN_PROGRESS`. Two half-open intervals overlap when one starts strictly before the other ends and the other starts strictly before the first ends. For the doctor, the nurse, and every equipment id, the candidate interval is `[prep_window_start, scheduled_end)`; an overlap on any of these resources rejects the request with `ERR_DOCTOR_CONFLICT`, `ERR_NURSE_CONFLICT`, or `ERR_EQUIPMENT_CONFLICT` (all HTTP 409). For the room, the candidate interval is the same on the start side but is extended on the end side by a sterilization gap of 15 minutes — so the room's effective occupation is `[prep_window_start, scheduled_end + 15min)`; overlap there is `ERR_ROOM_CONFLICT` (HTTP 409). For the anesthesia resource when present, the interval is `[scheduled_start, scheduled_end)` with neither the prep window nor the sterilization gap applied; overlap is `ERR_ANESTHESIA_CONFLICT` (HTTP 409). Each resource is therefore checked against a different interval shape — the room is the only resource that carries the sterilization pad, and anesthesia is the only resource that does not carry the prep window.

Concurrent appointment creations against the same resource are serialized on that resource's occupation: a second creation that requests the same operating room in overlapping windows is rejected with `ERR_ROOM_CONFLICT`; a second creation against the same doctor in overlapping windows is rejected with `ERR_DOCTOR_CONFLICT`; a second creation against the same anesthesia resource is rejected with `ERR_ANESTHESIA_CONFLICT`. Each is a first-writer-wins serialization against the live booked intervals.

Creating an appointment under an `APPROVED` plan first checks that no project in `locked_project_versions` has drifted — that is, every project's current `version` equals the value snapshotted at plan approval. If any project's version no longer matches the snapshot, the appointment request is rejected with `ERR_PLAN_STALE_REFERENCE` (HTTP 409); the same check applies to reschedule operations.

Reschedule is a self-loop from `SCHEDULED` to `SCHEDULED`, accessible to the consultant, that accepts a new `scheduled_start` plus optionally new `doctor_id`, `nurse_id`, `room_id`, `equipment_ids`, `anesthesia_resource_id`, and `version`. It increments `reschedule_count`, recomputes `scheduled_end` and `prep_window_start`, and re-runs the four-way match. A reschedule attempt when `reschedule_count` is already 3 is rejected with `ERR_RESCHEDULE_LIMIT` (HTTP 422). A reschedule when the parent plan is no longer `APPROVED`, or when project versions have drifted from the snapshot, is also rejected. The plan-stale-reference check applies to both appointment-create and reschedule.

An appointment in `SCHEDULED` may also be cancelled by the consultant (state advances to terminal `CANCELLED`) or — through the scheduled-time-elapsed sweep — auto-transitioned to terminal `NO_SHOW` when the server clock crosses `scheduled_end` plus 60 minutes while the appointment is still `SCHEDULED`. The check-in transition is performed by the assigned `Nurse` and moves the appointment from `SCHEDULED` to `CHECKED_IN`; the server time at check-in must lie within `[prep_window_start, scheduled_end)`, and a check-in attempt outside that window is rejected with `ERR_CHECKIN_OUTSIDE_WINDOW` (HTTP 422). Check-in creates an `OperativeRecord` shell whose `check_in_at` is set to the server time, and writes an audit entry of action `OP_CHECK_IN`.

### 3.5. Intra-Operative Records

The `OperativeRecord` is tied 1:1 to an `Appointment` by its `appointment_id`; it is an append-only log and so carries only `id` and `created_at`. It collects the chronological `procedure_log` of `{step_code, recorded_at, note}` entries (where `step_code` is `START`, `KEY_STEP`, or `END`), an array of `consumable_usage` entries of `{sku_id, lot_number, quantity, recorded_at}`, an array of `vital_sign_attachments` referencing asset ids of monitoring data files, an `incidents` array of `{severity, reported_at, note}` reports, and a `post_photo_ids` array of asset ids referencing post-procedure photo assets.

The attending physician's start action transitions the appointment from `CHECKED_IN` to `IN_PROGRESS`. The acting physician must equal the appointment's `doctor_id`; on success a procedure-log entry of `{step_code: START, recorded_at: now}` is appended and an audit entry with action `OP_START` is written. While the appointment is `IN_PROGRESS`, key-step entries may be appended by the attending physician via the key-step action which accepts a `note`; consumable usage may be recorded by the attending physician or the assigned nurse via the consumables action which accepts `sku_id`, `quantity`, and an optional `lot_number`; vital-sign data files may be attached by the assigned nurse via the vitals action which accepts an `asset_id`; and intra-operative incident reports may be appended by either the attending physician or the assigned nurse via the incidents action with `severity` and `note`. Every consumable-usage record for which the SKU's `requires_lot_tracking` is true must carry a non-empty `lot_number`; an attempt to record usage without a `lot_number` for such a SKU is rejected with `ERR_LOT_NUMBER_REQUIRED` (HTTP 422). Recording a consumable emits a `SyncEvent` of topic `PHARMA_TRACE` and kind `CONSUMABLE_USED`.

Ending the procedure is the attending physician's responsibility and transitions the appointment from `IN_PROGRESS` to the terminal `COMPLETED` status. The request body optionally carries `post_photo_ids` to attach the post-procedure photo bundle in one shot. End is permitted only when the procedure log contains exactly one `START` entry, every consumable-usage entry for a SKU with `requires_lot_tracking` true has a non-empty `lot_number`, and for every BOM entry of the appointment's project the cumulative recorded quantity of that SKU across the `consumable_usage` array is at least the BOM-required quantity. The `END` entry is appended to the procedure log with `recorded_at` equal to the server time, the appointment's `status` is set to `COMPLETED`, and four follow-up rows are auto-generated — one per stage `D1`, `W1`, `M1`, `M3`, all with `status` of `PENDING` and `due_at` computed from the server's current time plus the stage offset. A `SyncEvent` of topic `PHARMA_TRACE` and kind `CONSUMABLE_USED` is emitted for every consumable-usage entry, and an audit entry of action `OP_END` is written.

### 3.6. Follow-Up, Self-Reported Feedback, and Adverse Events

Each `FollowUp` is parented to an `Appointment` by `appointment_id` and carries a `stage` of `D1`, `W1`, `M1`, or `M3` (with the pair `appointment_id` plus `stage` being unique), a `due_at` computed at spawn time as the completed appointment's end-time plus the stage offset (1 day for `D1`, 7 days for `W1`, 30 days for `M1`, and 90 days for `M3`), a reminder dispatch `channel` of `CALL` or `IM`, a default `status` of `PENDING`, a self-reported `feedback` object (with keys `satisfaction` in 1..5, `symptoms`, and `notes`) defaulting to null, and an `adverse_event_filed` boolean defaulting to false.

The `Nurse` dispatches the reminder, transitioning the follow-up from `PENDING` to `REMINDED`; the server time must be at or after `due_at`. Reminder dispatch emits a `SyncEvent` with topic `IM` and kind `FOLLOWUP_REMINDER` (the `channel` value governs the message body but not the sync-event topic, which is always `IM`), and writes an audit entry of action `FOLLOWUP_REMINDED`. The owning customer then submits self-reported `feedback` (with `satisfaction`, optional `symptoms`, optional `notes`) which transitions the follow-up from `REMINDED` to the terminal `COMPLETED` and persists the feedback object. If the server clock crosses `due_at` plus 7 days while the follow-up is still `PENDING`, the time-driven sweep transitions it to the terminal `MISSED`.

The adverse-event trigger maps feedback to an auto-created `AdverseEvent`. The system reads `feedback.satisfaction` (a value in 1..5) and `feedback.symptoms` (an array of codes, possibly absent). The severe-symptom set is `{INFECTION, NECROSIS, ANAPHYLAXIS}`; the moderate-symptom set is `{PERSISTENT_PAIN, SWELLING_BEYOND_NORMAL, NUMBNESS}`. If any reported symptom is a member of the severe-symptom set, an adverse event is created with `severity` of `SEVERE`. Otherwise, if `satisfaction` equals 1 or any reported symptom is a member of the moderate-symptom set, an adverse event is created with `severity` of `MODERATE`. Otherwise, if `satisfaction` equals 2, an adverse event is created with `severity` of `MINOR`. Otherwise no adverse event is created. When an event is auto-created from feedback, `adverse_event_filed` is set to true on the originating follow-up and the new adverse event is opened in `OPEN`.

An adverse event carries `appointment_id` (originating appointment), `customer_id`, `severity` of `MINOR`, `MODERATE`, or `SEVERE`, a free-text `description`, a `status` of `OPEN`, `ESCALATED`, or `CLOSED` (defaulting to `OPEN`), and an `escalated_at` timestamp defaulting to null. A `SEVERE` event always escalates: when created with `severity` of `SEVERE` (whether manually filed or auto-from-feedback) it is moved from `OPEN` to `ESCALATED`. The escalate action — performed by the attending physician or by a senior physician — sets `escalated_at` to the server time, increments the customer's `adverse_event_count`, recomputes the customer's `risk_score` (with the new multiplier), and writes an audit entry of action `AE_ESCALATED`. The cascade depth is two: adverse-event escalate triggers customer risk-score recompute, and any future plan submission for that customer reads the new score when deciding `requires_senior_countersign`. Closing an `OPEN` event without escalation is permitted to the attending physician only when `severity` is `MINOR`; closing an `ESCALATED` event is reserved to a senior physician. Either close path moves the event to terminal `CLOSED` and writes an audit entry of action `AE_CLOSED`. Manually filing an adverse event accepts `appointment_id`, `severity`, and `description` and is open to the attending physician or the assigned nurse; manual filing also runs the customer-risk-score recompute side effect.

### 3.7. Installment Financing, KYC, Default, and Medical-Event Refund

An `InstallmentPlan` is created against an `APPROVED` `TreatmentPlan` by a `FinanceOfficer` or by a `Consultant`. The request body carries `treatment_plan_id`, `downpayment_cents`, `term_months`, and a `finance_partner_id` identifying the third-party consumer-finance institution. Exactly one `InstallmentPlan` exists per `TreatmentPlan`; a second creation racing on the same parent is rejected with `ERR_INSTALLMENT_ALREADY_EXISTS` (HTTP 409). The `term_months` must be one of 3, 6, 12, or 24 — any other value yields `ERR_INVALID_INSTALLMENT_TERM` (HTTP 422). The `downpayment_cents` must lie within the inclusive range from 0 to `TreatmentPlan.final_total_cents`; an out-of-range downpayment is rejected with `ERR_DOWNPAYMENT_OUT_OF_RANGE` (HTTP 422). The plan opens with `status` of `PENDING_KYC`, a `principal_cents` computed as `TreatmentPlan.final_total_cents` minus `downpayment_cents`, a `paid_amount_cents` of 0, a `default_strike_count` of 0, and an empty `schedule`. The fields `apr_bps` and `schedule` are written when the plan is activated.

Activation moves the plan from `PENDING_KYC` to `ACTIVE` and is reserved to the `FinanceOfficer`. It requires the parent `TreatmentPlan.status` to be `APPROVED`, the customer's `kyc_status` to be `VERIFIED`, and the customer's `credit_score` to be at least the term-specific minimum: 500 for a 3-month term, 600 for 6 months, 700 for 12 months, and 750 for 24 months. A failed KYC-or-credit gate is reported as `ERR_KYC_OR_CREDIT_FAIL` (HTTP 422). On activation the system generates `schedule` and writes `apr_bps`, then emits a `SyncEvent` of topic `FINANCE_PARTNER` and kind `PLAN_ACTIVATED`.

The annual percentage rate in basis points is selected from a term-keyed table: 0 for a 3-month term (a promotional zero-interest tier), 600 for 6 months, 1200 for 12 months, and 1800 for 24 months. The monthly rate is `apr_bps` divided by 10000 divided by 12. With principal `P` equal to `principal_cents` and term `n` equal to `term_months`, the monthly total in cents is computed by the standard annuity formula — principal times monthly rate times one-plus-monthly-rate raised to the power n, divided by one-plus-monthly-rate raised to the power n minus one — and that value is rounded half-up to integer cents. Then for each period from 1 to n-1, the period's interest in cents is the running balance times the monthly rate rounded half-up, and the period's principal in cents is the monthly total minus the period's interest; the running balance is reduced by the period's principal. The final period absorbs any residual: its principal in cents equals the remaining running balance exactly, and its total cents equals its principal plus its interest, so that the sum of per-period principals across the schedule equals the original principal exactly. The `schedule` is therefore an array of `{index, due_date, principal_cents, interest_cents, total_cents, status}` entries with each `due_date` equal to the activation timestamp plus `index` months and each `status` initialized to `PENDING`. For the zero-APR 3-month tier the formula degenerates: every period's `interest_cents` is 0 and every monthly total is the original principal divided by 3 rounded half-up with the last period absorbing the residual. For the interest-bearing tiers (6, 12, or 24 months) the full annuity formula applies and every non-final period has a strictly positive `interest_cents`.

Payments are recorded via the payments action by the owning `Customer` or by a `FinanceOfficer`. The request body carries `amount_cents`, an `external_ref` reference from the payment or finance partner, and an optional `prepay` flag. The payment must be strictly greater than 0 and not exceed the remaining unpaid balance (the sum of `total_cents` for schedule entries whose `status` is not `PAID`); a payment outside this range is rejected with `ERR_PAYMENT_AMOUNT_INVALID` (HTTP 422). Payments mark schedule entries `PAID` in due-date order, update `paid_amount_cents` to the sum of `total_cents` for entries with `status` equal to `PAID`, and emit a `SyncEvent` of topic `PAYMENT`. A final settlement that brings every schedule entry to `PAID` transitions the installment plan from `ACTIVE` to the terminal `COMPLETED` and emits a `SyncEvent` of topic `FINANCE_PARTNER` and kind `PLAN_SETTLED`.

Default handling is time-driven. When the server clock advances past a `PENDING` schedule entry's `due_date` plus the 7-day grace period, the installment plan transitions from `ACTIVE` to `IN_DEFAULT`; `default_strike_count` is incremented, a `PaymentEvent` of kind `COLLECTION_NOTICE` is written, and a `SyncEvent` of topic `FINANCE_PARTNER` and kind `DEFAULT_STRIKE` is emitted. While in `IN_DEFAULT`, a payment that covers every overdue `PENDING` installment in full restores the plan to `ACTIVE`, marks the overdue entries `PAID`, and updates `paid_amount_cents`.

A medical-event refund is initiated through the refund-medical-event action by a `FinanceOfficer`, which carries an `adverse_event_id`. The action is permitted when the referenced `AdverseEvent.severity` is `SEVERE`. It transitions the installment plan from `ACTIVE` to terminal `REFUNDED`, writes a `PaymentEvent` of kind `REFUND` for the current `paid_amount_cents`, marks every remaining `PENDING` schedule entry's status field on the entry as `CANCELLED`, emits a `SyncEvent` of topic `FINANCE_PARTNER` and kind `REFUND_INITIATED`, and writes an audit entry. The same `REFUNDED` outcome is reached without a manual call when a treatment-plan cancellation cascades through an `ACTIVE` installment plan as described in §3.3. `PaymentEvent` rows are append-only and carry only `id` and `created_at`; each row records the parent `installment_plan_id`, the `kind` (one of `INSTALLMENT_PAID`, `PREPAYMENT`, `REFUND`, `COLLECTION_NOTICE`), the `amount_cents` (always positive — the sign is implied by `kind`), an `external_ref` from the partner, and a server-side `recorded_at` timestamp.

### 3.8. Test-Clock Capability and Outbox Inspection

An admin-only test-driving capability advances the server's logical clock by a supplied `seconds` value and, after advancing, evaluates the three sweeps described in §2.10 in order. The `AuditEntry` listing (filterable by `subject_type`, `subject_id`, and `action`) is available to `MedicalDirector` and `SeniorPhysician`; the `SyncEvent` listing (filterable by `topic` and `kind`) is available to `MedicalDirector` and `FinanceOfficer`.

## 4. Endpoint Definitions

All endpoints are mounted under the `/aesthetics` prefix except the test-driving `/_clock/advance` capability. New-resource creation endpoints return HTTP 201; modifications (state transitions, edits, and informational reads) return HTTP 200. Every endpoint inherits the validation order described in §2.6, the response envelope in §2.2, and the pagination contract in §2.3.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /aesthetics/projects | Create a project in DRAFT. | MedicalDirector, Consultant |
| PATCH | /aesthetics/projects/{id} | Edit a project in DRAFT or UNDER_REVIEW. | MedicalDirector, Consultant |
| POST | /aesthetics/projects/{id}/submit | Submit project for medical-director review. | MedicalDirector, Consultant |
| POST | /aesthetics/projects/{id}/approve | Approve and publish (UNDER_REVIEW → ON_SHELF). | MedicalDirector |
| POST | /aesthetics/projects/{id}/reject | Reject and send back to DRAFT. | MedicalDirector |
| POST | /aesthetics/projects/{id}/take-off-shelf | Take project off shelf. | MedicalDirector |
| POST | /aesthetics/projects/{id}/return-to-shelf | Restore project to shelf. | MedicalDirector |
| GET | /aesthetics/projects/{id} | Fetch a single project. | MedicalDirector, Consultant, AttendingPhysician, SeniorPhysician, Nurse, FinanceOfficer |
| GET | /aesthetics/projects | List projects with filters (category, status, risk_level). | MedicalDirector, Consultant, AttendingPhysician, SeniorPhysician, Nurse, FinanceOfficer |
| POST | /aesthetics/projects/{id}/contraindication-rules | Attach a contraindication rule to a project. | MedicalDirector |
| GET | /aesthetics/projects/{id}/contraindication-rules | List rules for a project. | MedicalDirector, Consultant, AttendingPhysician, SeniorPhysician |
| POST | /aesthetics/consumable-skus | Register a consumable or drug SKU. | MedicalDirector |
| GET | /aesthetics/consumable-skus | List SKUs. | MedicalDirector, Consultant, AttendingPhysician, Nurse |
| POST | /aesthetics/rooms | Register an operating/procedure room. | MedicalDirector |
| GET | /aesthetics/rooms | List rooms with filter on room_kind and is_active. | MedicalDirector, Consultant, AttendingPhysician, Nurse |
| POST | /aesthetics/customers | Create a customer profile. | Consultant |
| PATCH | /aesthetics/customers/{id} | Update a customer's declarative fields; recomputes risk_score. | Consultant, Customer |
| POST | /aesthetics/customers/{id}/kyc | Submit and verify KYC + credit check. | FinanceOfficer |
| GET | /aesthetics/customers/{id} | Fetch a customer. | Consultant, AttendingPhysician, SeniorPhysician, Nurse, FinanceOfficer, Customer |
| POST | /aesthetics/plans | Create a plan in DRAFT. | Consultant |
| PATCH | /aesthetics/plans/{id} | Edit a DRAFT plan; recomputes provisional total and countersign flag. | Consultant |
| POST | /aesthetics/plans/{id}/submit | Submit DRAFT plan (DRAFT → SUBMITTED). | Consultant |
| POST | /aesthetics/plans/{id}/sign-consent | Customer signs informed consent on a SUBMITTED plan. | Customer |
| POST | /aesthetics/plans/{id}/approve | Attending physician approves a non-countersign plan. | AttendingPhysician |
| POST | /aesthetics/plans/{id}/countersign | Senior physician countersigns when required. | SeniorPhysician |
| POST | /aesthetics/plans/{id}/reject | Attending rejects plan (SUBMITTED → REJECTED). | AttendingPhysician |
| POST | /aesthetics/plans/{id}/return-to-draft | Consultant pulls a SUBMITTED plan back to DRAFT. | Consultant |
| POST | /aesthetics/plans/{id}/cancel | Cancel an APPROVED plan with cascade. | AttendingPhysician |
| GET | /aesthetics/plans/{id} | Fetch a plan. | Consultant, AttendingPhysician, SeniorPhysician, Customer, FinanceOfficer |
| GET | /aesthetics/plans | List plans (filter customer_id, status). | Consultant, AttendingPhysician, SeniorPhysician, FinanceOfficer |
| POST | /aesthetics/appointments | Create an appointment with four-way matching. | Consultant |
| POST | /aesthetics/appointments/{id}/reschedule | Reschedule within the reschedule limit. | Consultant |
| POST | /aesthetics/appointments/{id}/cancel | Cancel a SCHEDULED appointment. | Consultant |
| POST | /aesthetics/appointments/{id}/check-in | Nurse checks in within the prep window. | Nurse |
| POST | /aesthetics/appointments/{id}/op-records/start | Mark procedure START (CHECKED_IN → IN_PROGRESS). | AttendingPhysician |
| POST | /aesthetics/appointments/{id}/op-records/key-step | Append a KEY_STEP entry to the procedure log. | AttendingPhysician |
| POST | /aesthetics/appointments/{id}/op-records/consumables | Record consumable / drug usage with lot-number traceability. | AttendingPhysician, Nurse |
| POST | /aesthetics/appointments/{id}/op-records/vitals | Attach a vital-sign data asset. | Nurse |
| POST | /aesthetics/appointments/{id}/op-records/incidents | Record an intra-operative incident. | AttendingPhysician, Nurse |
| POST | /aesthetics/appointments/{id}/op-records/end | Mark procedure END; spawns four FollowUps. | AttendingPhysician |
| GET | /aesthetics/appointments/{id} | Fetch an appointment. | Consultant, AttendingPhysician, Nurse, Customer |
| GET | /aesthetics/appointments | List appointments with filters. | Consultant, AttendingPhysician, Nurse, FinanceOfficer |
| POST | /aesthetics/followups/{id}/remind | Dispatch a follow-up reminder via the configured channel. | Nurse |
| POST | /aesthetics/followups/{id}/feedback | Customer submits self-reported feedback. | Customer |
| GET | /aesthetics/followups/{id} | Fetch a follow-up. | Consultant, AttendingPhysician, Nurse, Customer |
| GET | /aesthetics/followups | List follow-ups (filter appointment_id, stage, status). | Consultant, AttendingPhysician, Nurse |
| POST | /aesthetics/adverse-events | Manually file an adverse event. | AttendingPhysician, Nurse |
| POST | /aesthetics/adverse-events/{id}/escalate | Escalate AE to medical-quality committee. | AttendingPhysician, SeniorPhysician |
| POST | /aesthetics/adverse-events/{id}/close | Close an adverse event. | AttendingPhysician, SeniorPhysician |
| GET | /aesthetics/adverse-events | List adverse events. | AttendingPhysician, SeniorPhysician, MedicalDirector |
| POST | /aesthetics/installments | Create an installment plan for an APPROVED treatment plan. | FinanceOfficer, Consultant |
| POST | /aesthetics/installments/{id}/activate | Activate installment plan (PENDING_KYC → ACTIVE). | FinanceOfficer |
| POST | /aesthetics/installments/{id}/payments | Record an installment payment or prepayment. | Customer, FinanceOfficer |
| POST | /aesthetics/installments/{id}/refund-medical-event | Issue refund triggered by a SEVERE adverse event. | FinanceOfficer |
| GET | /aesthetics/installments/{id} | Fetch an installment plan. | FinanceOfficer, Customer, Consultant |
| GET | /aesthetics/installments | List installment plans. | FinanceOfficer, Consultant |
| GET | /aesthetics/audit-entries | List audit entries with filters (subject_type, subject_id, action). | MedicalDirector, SeniorPhysician |
| GET | /aesthetics/sync-events | List emitted sync events (filter topic, kind). | MedicalDirector, FinanceOfficer |
| POST | /_clock/advance | Advance server clock by `seconds` (test-only); triggers sweeps. | MedicalDirector |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|---|---|
| ERR_UNAUTHENTICATED | 401 |
| ERR_FORBIDDEN | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_INVALID_INPUT | 400 |
| ERR_PAGINATION_OUT_OF_RANGE | 400 |
| ERR_INVALID_STATE | 409 |
| ERR_VERSION_CONFLICT | 409 |
| ERR_CUSTOMER_UNDERAGE | 422 |
| ERR_ABSOLUTE_CONTRAINDICATION | 422 |
| ERR_SEGREGATION_VIOLATION | 422 |
| ERR_CONSENT_NOT_SIGNED | 422 |
| ERR_LOT_NUMBER_REQUIRED | 422 |
| ERR_DOCTOR_NOT_QUALIFIED | 422 |
| ERR_PROJECT_NOT_ON_SHELF | 422 |
| ERR_PROJECT_IN_USE | 409 |
| ERR_ANESTHESIA_REQUIREMENT_MISMATCH | 422 |
| ERR_ROOM_KIND_MISMATCH | 422 |
| ERR_DOCTOR_CONFLICT | 409 |
| ERR_NURSE_CONFLICT | 409 |
| ERR_ROOM_CONFLICT | 409 |
| ERR_EQUIPMENT_CONFLICT | 409 |
| ERR_ANESTHESIA_CONFLICT | 409 |
| ERR_CHECKIN_OUTSIDE_WINDOW | 422 |
| ERR_RESCHEDULE_LIMIT | 422 |
| ERR_PLAN_ITEMS_OUT_OF_RANGE | 422 |
| ERR_PLAN_STALE_REFERENCE | 409 |
| ERR_INVALID_INSTALLMENT_TERM | 422 |
| ERR_KYC_OR_CREDIT_FAIL | 422 |
| ERR_DOWNPAYMENT_OUT_OF_RANGE | 422 |
| ERR_PAYMENT_AMOUNT_INVALID | 422 |
| ERR_INSTALLMENT_ALREADY_EXISTS | 409 |
