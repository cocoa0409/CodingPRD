# Boiler & Pressure-Vessel Inspection API — Product Requirements Document

## 1. Introduction

Boilers and pressure vessels are among the most heavily regulated pieces of industrial equipment in service, because a single catastrophic rupture can cost lives. This document specifies the API for a jurisdictional inspection registry that tracks a pressure-retaining vessel across its entire regulated life: from the moment an owner first registers it, through the assignment of a jurisdiction registration number, the scheduling and performance of periodic and incident-triggered inspections, the raising and clearing of deficiencies, the billing and collection of inspection fees, and finally the issuance and renewal of the operating certificate that legally permits the vessel to remain in service.

The system must reconcile several parties whose duties are deliberately kept separate. A jurisdiction administrator operates the public registry and holds authority over registration, commissioning, scheduling, and money. A vessel owner is responsible for the physical equipment, for arranging repairs, and for paying fees. A certified inspector — employed either directly by the jurisdiction or by an insurance company that underwrites the vessel — performs the physical inspection, files the statutory National Board report, and raises or clears deficiencies. A recurring theme throughout the specification is that the inspector who discovers a problem may not be the same person who later certifies it as fixed; this segregation of duties is a first-class safety control, not an administrative nicety.

Two further themes pervade the design. First, the platform is **temporal**: certificate validity windows, insurance coverage windows, inspector scheduling conflicts, and age-based risk all depend on a controllable logical clock rather than wall-clock time, so that every time-dependent rule is testable and deterministic. Second, the platform is **conservational**: fees collected into a jurisdiction ledger, counts of open deficiencies, and the derived risk of a vessel must all remain internally consistent as operations cascade across related resources. The sections that follow define the global contracts first, then the business workflows in which the individual rules are scattered.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request to the API (with no exceptions) must carry two headers identifying the caller: `X-User-ID` and `X-User-Role`. If either header is missing, or if `X-User-Role` does not name one of the three roles defined below, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). When the headers are well-formed but the named role is not permitted to invoke the requested operation (per the authorization matrix summarized in §4), the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The three roles are spelled exactly `JurisdictionAdmin`, `Owner`, and `Inspector`.

- **`JurisdictionAdmin`** is an *opaque* operator identity. When `X-User-Role` is `JurisdictionAdmin`, the `X-User-ID` value is an operator identifier that is not tied to any persisted entity; the server may record it where a workflow calls for it, but it never compares it to any entity's `id`. A `JurisdictionAdmin` administers the registry: it creates jurisdictions, insurance companies, owners, and inspectors; commissions and suspends inspectors; registers, retires, and reinstates vessels; records and manages insurance policies; schedules and cancels inspections; issues, revokes, and expires certificates; creates fee invoices and refunds them; and drives the logical clock.
- **`Owner`** is an *entity-backed* identity. When `X-User-Role` is `Owner`, `X-User-ID` is the `id` of the acting `Owner` entity; ownership checks on any resource that references an `Owner` compare that resource's owning foreign key to `X-User-ID`. An `Owner` registers its own vessels, opens and manages repair orders on vessels it owns, pays fee invoices billed against its own vessels, and files incident reports.
- **`Inspector`** is an *entity-backed* identity. When `X-User-Role` is `Inspector`, `X-User-ID` is the `id` of the acting `Inspector` entity; ownership checks compare an inspection's assigned inspector to `X-User-ID`. An `Inspector` records inspection results for inspections assigned to it, files National Board reports, and raises, withdraws, and reinspects deficiencies.

When an entity-backed role acts on a resource it does not own — an `Owner` operating on a vessel, repair order, or fee invoice belonging to a different owner, or an `Inspector` recording the result of an inspection assigned to a different inspector — the request is rejected with `ERR_OWNERSHIP_MISMATCH` (HTTP 403).

All three roles may perform every read (`GET`) operation. Write authority is restricted as described above and enumerated in the §4 endpoint table.

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

Every list (`GET` collection) endpoint is paginated through two query parameters, `limit` and `offset`. The `limit` parameter controls how many records are returned; it defaults to 10 when omitted, may be no smaller than 1, and may be no larger than 100. The `offset` parameter is the zero-based index of the first record to return; it defaults to 0 and may not be negative. Results are always sorted by `created_at` in ascending order (oldest first), so that pagination is stable as new records are appended; because the logical clock can stamp many records with an identical `created_at`, ties are broken by insertion (creation) order. A `limit` or `offset` that is non-integer or falls outside these bounds is rejected with `ERR_INVALID_REQUEST`.

For list responses, the `meta` object carries the pagination fields `limit`, `offset`, `total_count`, and `has_more`: `total_count` is the total number of records matching the query before pagination is applied, and `has_more` is true exactly when records remain beyond the current page.

### 2.4. Common Resource Properties and Identity

Every persisted resource carries a server-minted `id`, which is a UUID string with no type prefix. Every resource also carries a `created_at` timestamp recording when it was created. Timestamps throughout the system are ISO 8601 UTC values with three fractional (millisecond) digits.

Most resources additionally carry an `updated_at` timestamp and an integer `version`. The `version` starts at 1 on creation and increments by exactly 1 on every mutation of that resource; `updated_at` is refreshed to the clock time of each mutation. These two fields are the backbone of both change tracking and the optimistic-concurrency mechanism described in §2.6. There is one exception: the National Board report is an append-only filing that carries only `id` and `created_at` — it has neither an `updated_at` nor a `version` field, because it is never mutated after it is filed.

Path parameters are the URL-embedded identifiers of the addressed resource — `jurisdictionId`, `insuranceCompanyId`, `ownerId`, `inspectorId`, `vesselId`, `policyId`, `inspectionId`, `reportId`, `deficiencyId`, `repairOrderId`, `feeInvoiceId`, `certificateId`, and `incidentId`. Because the topology is flat (resources are peer collections joined by foreign-key fields rather than nested under one another in the URL), each path names a single resource. When a request references resources — first the identifiers embedded in the path, then any foreign-key fields carried in the body — the server validates their existence left to right, and any reference to a non-existent resource is rejected with `ERR_NOT_FOUND` (HTTP 404).

### 2.5. The Logical Clock and Temporal Windowing

The server runs on a **logical clock** rather than wall-clock time. On startup the clock reads exactly `2026-03-01T00:00:00Z`, and before any adjustment it never falls back to real time. A `JurisdictionAdmin` may advance (or set) the clock by supplying a target instant `to_iso8601`; the operation returns the new clock value as `now`. Every interval, expiry, coverage, and age rule in this specification reads "now" from this logical clock.

Two interval conventions must be distinguished precisely, because their boundary behavior differs. An **inspector's scheduled occupancy** runs over a *half-open* interval from `scheduled_start` (inclusive) up to `scheduled_end` (exclusive): two inspections that merely touch — where one ends at the exact instant the next begins — do **not** conflict. An **insurance coverage** window, by contrast, runs over a *closed* interval from `coverage_start` through `coverage_end`, both endpoints inclusive: two coverage windows that touch at a shared endpoint **do** conflict.

### 2.6. Optimistic Concurrency Control on Certificate Issuance

Certificate issuance is guarded by optimistic concurrency control on the vessel. A request to issue a certificate must carry `expected_vessel_version`, a non-optional field carrying the `version` of the target vessel that the client last observed. Before the certificate is created, the server compares `expected_vessel_version` against the vessel's current `version`. If they do not match — meaning another writer has advanced the vessel's version since the client last read it, for example by already issuing a certificate that legitimately became the vessel's current certificate and bumped its version — the issuance is rejected with `ERR_STALE_VESSEL_VERSION` (HTTP 412). This prevents a client working from a stale view from silently creating a second `ACTIVE` certificate on the same vessel. Certificate issuance is the only endpoint that takes a version field; no other operation requires an expected-version input.

### 2.7. Validation Ordering and Error Precedence

When a single request could fail multiple checks, the checks are evaluated in a fixed priority order and the first failure determines the returned error. The order is:

1. **Authentication** — headers present and `X-User-Role` a known role, else `ERR_UNAUTHENTICATED` (401).
2. **Authorization** — the role may call this endpoint, else `ERR_UNAUTHORIZED` (403).
3. **Existence** — every path identifier and then every body foreign key resolves, else `ERR_NOT_FOUND` (404).
4. **Ownership** — for an entity-backed acting role, `X-User-ID` equals the owning foreign key of the target (an `Owner` acting on its own `Vessel`, `RepairOrder`, or `FeeInvoice`; an `Inspector` acting on its own `Inspection`), else `ERR_OWNERSHIP_MISMATCH` (403). This is enforced on repair-order creation and completion, fee-invoice payment, inspection result recording, incident filing, and deficiency withdrawal (where the acting `Inspector` must be the raising inspector). It is deliberately **not** enforced on raising a deficiency, filing a National Board report, repair-order cancellation, or deficiency reinspection.
5. **State** — the target resource is in a state that permits the transition, else `ERR_INVALID_STATE` (409); at the same priority, the optimistic-concurrency check on certificate issuance yields `ERR_STALE_VESSEL_VERSION` (412).
6. **Business safety** — vessel inspectability yields `ERR_VESSEL_NOT_INSPECTABLE` (409) and the open-critical-deficiency bar on certificate issuance yields `ERR_CRITICAL_DEFICIENCY_OPEN` (409).
7. **Business referential** — insurance-inspector coordination yields `ERR_INSURANCE_COORDINATION_INVALID` (409) and jurisdiction-inspector commissioning yields `ERR_INSPECTOR_NOT_COMMISSIONED` (409).
8. **Business constraint** — segregation of duties yields `ERR_SEGREGATION_OF_DUTIES` (409); uniqueness collisions yield `ERR_DUPLICATE_UNIQUE_FIELD` (409); an unrepairable deficiency yields `ERR_DEFICIENCY_NOT_REPAIRABLE` (409).
9. **Business temporal** — inspector double-booking yields `ERR_INSPECTOR_DOUBLE_BOOKED` (409) and insurance coverage overlap yields `ERR_POLICY_COVERAGE_OVERLAP` (409).
10. **Business fiscal** — the fee-paid precondition on certificate issuance yields `ERR_FEE_NOT_PAID` (402).
11. **Request validity** — body field types, enum membership, required-field presence, and cross-field ranges, else `ERR_INVALID_REQUEST` (400). Primitive, enum, and required-field checks conceptually run early (before body foreign-key existence), but all such malformed-body failures share this one error id.

The two remaining state-boundary errors — `ERR_CERTIFICATE_NOT_DUE` (409) when a certificate expire is attempted before it is due, and `ERR_POLICY_NOT_EXPIRABLE` (409) when a policy expire is attempted too early — are described with their respective workflows in §3.

### 2.8. Monetary Precision and the Jurisdiction Fee Ledger

All monetary amounts are stored as whole integer cents. Wherever a fee is computed, an administrative surcharge percentage — the jurisdiction's `admin_fee_pct`, which defaults to 0.075 (7.5%) and must lie between 0 and 1 inclusive — is applied to each individual line item, that line is rounded to whole cents using round-half-up, and only then are the rounded lines summed. Rounding is applied per line and never to a running total; the sum of already-rounded lines is the final fee. The precise fee formula and its line items live in §3.7.

Each jurisdiction maintains a conserved money quantity, `collected_fees_cents`, defined as the sum of `amount_paid_cents` less the sum of `refunded_cents` across every fee invoice whose vessel belongs to that jurisdiction. This ledger is credited the instant an invoice is paid and debited the instant it is refunded, so that a pay followed by a refund nets to zero. The ledger is never touched by voiding an unpaid invoice, because such an invoice was never collected.

### 2.9. Parallel Status Dimensions and Cascade Consistency

A vessel carries two **independent** status dimensions that evolve separately. The `registration_status` dimension is a regulatory-lifecycle axis with values `DRAFT`, `REGISTERED`, and `RETIRED`. The `service_status` dimension is an operational axis with values `NOT_IN_SERVICE`, `IN_SERVICE`, `RESTRICTED`, `SUSPENDED`, and `OUT_OF_SERVICE`. Registering a vessel changes only its registration axis and leaves it `NOT_IN_SERVICE`; putting a vessel into or out of service moves only the service axis.

Many operations mutate more than one resource. Whenever a workflow changes a vessel's derived state, the vessel's computed fields — `open_deficiency_count`, `open_critical_deficiency_count`, `risk_score_standard`, and `risk_score_forecast` — are recomputed, and where a scaffold transition says so the vessel's `version` is incremented and its `updated_at` refreshed. The specific cascades (an incident that suspends a vessel and revokes its certificate, a certificate revocation that cancels scheduled inspections, a final reinspection that returns a vessel to service) are described in §3 alongside the operations that trigger them; the cross-cutting rule is simply that these secondary effects always accompany the primary transition and are never deferred.

## 3. Business Logic & Workflows

### 3.1. Building the Registry: Jurisdictions, Insurers, Owners, and Inspectors

Before any vessel can be tracked, a `JurisdictionAdmin` populates the reference registry. A **jurisdiction** is created with a two-letter `code` (unique, uppercase A–Z, exactly two characters), a human-readable `name`, an optional `admin_fee_pct` (the administrative surcharge already discussed, defaulting to 0.075 and constrained to the range 0 through 1 inclusive), and an optional `interval_months_override`. The override, when supplied, must be null or an integer of at least 1; when set, it replaces the class-default inspection interval for every vessel registered in that jurisdiction, and when left null the class default applies. A jurisdiction also exposes its running `collected_fees_cents` ledger. Jurisdictions may be listed (optionally filtered by `code`) or fetched individually. A jurisdiction created with a `code` that already exists collides on uniqueness and is rejected with `ERR_DUPLICATE_UNIQUE_FIELD`.

An **insurance company** is created with a legal `name` and a `nb_accreditation_number` (its National Board accreditation number), the latter required to be unique. Insurance companies may be listed or fetched. An **owner** is created with a `name` and a `contact_email`, and may likewise be listed or fetched.

An **inspector** is registered with a `name`, a unique `commission_number` (the National Board commission number), an `inspector_type` of either `JURISDICTION` (state- or province-employed) or `INSURANCE` (insurance-company-employed), an optional `insurance_company_id`, and an optional `commissioning_jurisdiction_id` naming the jurisdiction in which the inspector holds or seeks a commission. The `insurance_company_id` is required when `inspector_type` is `INSURANCE` and must be null when `inspector_type` is `JURISDICTION`. A duplicate `commission_number` is rejected with `ERR_DUPLICATE_UNIQUE_FIELD`. Every inspector begins life in coordination `status` `PENDING`. Inspectors may be listed — filterable by `insurance_company_id`, by `commissioning_jurisdiction_id`, or by `status` — or fetched individually.

An inspector's coordination status is advanced by the `JurisdictionAdmin`. Commissioning moves an inspector from `PENDING` to `COMMISSIONED`; it requires that the inspector's `commissioning_jurisdiction_id` is set, and, for an `INSURANCE` inspector, that its `insurance_company_id` is set. These two preconditions are checked only on the `PENDING → COMMISSIONED` transition (re-commissioning from `SUSPENDED` re-checks neither), and an unmet precondition is rejected with `ERR_INVALID_STATE`. Suspending an inspector moves it from `COMMISSIONED` to `SUSPENDED` (permitted only from `COMMISSIONED`). A suspended inspector may be re-commissioned, moving from `SUSPENDED` back to `COMMISSIONED`. Each of these three transitions increments the inspector's `version` by 1; attempting one from a state that does not permit it fails with `ERR_INVALID_STATE`.

### 3.2. Vessel Registration and the Registration Lifecycle

A vessel enters the system when an `Owner` registers it. The creation payload identifies the `owner_id` (which must equal the caller's `X-User-ID`), the `jurisdiction_id` of registration, the `manufacturer`, the `national_board_number` stamped on the vessel by the manufacturer (unique across all vessels), the `vessel_class` (one of `POWER_BOILER`, `HEATING_BOILER`, or `PRESSURE_VESSEL`), the `mawp_psig` (maximum allowable working pressure in psig, an integer of at least 1), and the `installed_at` installation date used later for age-based risk. A newly created vessel starts with `registration_status` `DRAFT`, `service_status` `NOT_IN_SERVICE`, a null `jurisdiction_number`, a null `current_certificate_id`, zero for both `open_deficiency_count` and `open_critical_deficiency_count`, and null risk scores. A duplicate `national_board_number` is rejected with `ERR_DUPLICATE_UNIQUE_FIELD`. Vessels may be listed — filterable by `owner_id`, `jurisdiction_id`, `current_certificate_id`, `registration_status`, or `service_status` — or fetched individually, the single-vessel view exposing the computed `risk_score_standard`, `risk_score_forecast`, the deficiency counts, `current_certificate_id`, and `jurisdiction_number`.

Registration of a vessel is performed by a `JurisdictionAdmin` and advances `registration_status` from `DRAFT` to `REGISTERED`. It is permitted only when the vessel is currently `DRAFT` and its `national_board_number` is present and unique. As a side effect it assigns the vessel's `jurisdiction_number`, formed as the jurisdiction's `code`, a hyphen, and the next six-digit zero-padded sequence number within that jurisdiction (so the first vessel registered in jurisdiction `CA` receives `CA-000001`). Registration increments the vessel's `version` by 1 and leaves the service axis untouched at `NOT_IN_SERVICE`. Attempting to register a vessel that is not `DRAFT` fails with `ERR_INVALID_STATE`.

Retiring a vessel is performed by a `JurisdictionAdmin` and advances `registration_status` from `REGISTERED` to `RETIRED`, the terminal registration state. It is permitted only when the vessel is `REGISTERED` and its `service_status` is not `SUSPENDED`. Retirement cascades: if the vessel holds an `ACTIVE` certificate, that certificate is transitioned to `REVOKED` (running the full revocation cascade of §3.7 — the vessel's `SCHEDULED` non-`SPECIAL` inspections are cancelled and `current_certificate_id` is cleared); the vessel's `service_status` is set to `OUT_OF_SERVICE`; and the vessel's `version` is incremented by 1. Reinstatement — returning a `SUSPENDED` vessel to service — is covered in §3.8 with the incident cascade that suspends it.

### 3.3. Insurance Coverage and Inspector Coordination

An insurance policy binds a vessel to an insurer for a coverage window. A `JurisdictionAdmin` records a policy by supplying the `vessel_id`, the `insurance_company_id`, and the coverage window endpoints `coverage_start` and `coverage_end`, which together form the closed interval described in §2.5. A new policy starts in `status` `ACTIVE`. Policies may be listed — filterable by `vessel_id`, `insurance_company_id`, or `status` — or fetched individually.

Because coverage is a closed interval, a new `ACTIVE` policy on a vessel may not overlap any existing `ACTIVE` policy on the same vessel, and two windows that share an endpoint (where an existing policy's `coverage_end` equals the new policy's `coverage_start`) are treated as overlapping. A conflicting policy is rejected with `ERR_POLICY_COVERAGE_OVERLAP`. A `JurisdictionAdmin` may cancel an `ACTIVE` policy, moving it to `CANCELLED`, or expire an `ACTIVE` policy, moving it to `EXPIRED`; both `CANCELLED` and `EXPIRED` are terminal. Cancellation is permitted whenever the policy is `ACTIVE`. Expiry additionally requires that the logical clock now is strictly after `coverage_end` (past the inclusive closed-interval end); attempting to expire before that instant is rejected with `ERR_POLICY_NOT_EXPIRABLE`, and attempting either transition from a non-`ACTIVE` policy fails with `ERR_INVALID_STATE`. Each policy transition increments the policy's `version` by 1.

The distinction between a jurisdiction inspector and an insurance inspector matters at scheduling time. When an inspection is assigned to a `JURISDICTION` inspector, that inspector must be `COMMISSIONED` in the vessel's jurisdiction — its `commissioning_jurisdiction_id` must equal the vessel's `jurisdiction_id` — or the schedule attempt is rejected with `ERR_INSPECTOR_NOT_COMMISSIONED`. When an inspection is assigned to an `INSURANCE` inspector, a stricter coordination check applies: the inspector must be `COMMISSIONED`, its `commissioning_jurisdiction_id` must equal the vessel's `jurisdiction_id`, and there must exist an `ACTIVE` insurance policy issued by the inspector's own insurer (its `insurance_company_id`) that covers the vessel with `coverage_start` at or before the inspection's `scheduled_start` and `coverage_end` at or after that same `scheduled_start`. If any of these conditions fails, the schedule attempt is rejected with `ERR_INSURANCE_COORDINATION_INVALID`.

### 3.4. Scheduling Inspections

Scheduling an inspection is a `JurisdictionAdmin` operation. The payload names the `vessel_id` under inspection, the assigned `inspector_id`, the `inspection_type` (one of `INTERNAL`, `EXTERNAL`, or `SPECIAL`, the last being incident-triggered), and the occupancy window `scheduled_start` and `scheduled_end`. A new inspection begins in `status` `SCHEDULED`, records `result_recorded_at` as null, and derives its `is_special` flag as true exactly when `inspection_type` is `SPECIAL`. Inspections may be listed — filterable by `vessel_id`, `inspector_id`, or `status` — or fetched individually.

A vessel is safe to inspect only when its `registration_status` is `REGISTERED` and its `service_status` is one of `IN_SERVICE`, `RESTRICTED`, or `NOT_IN_SERVICE`. A vessel that is `SUSPENDED` or `OUT_OF_SERVICE` may not be scheduled for an ordinary inspection; the sole exception is that an inspection whose `inspection_type` is `SPECIAL` may proceed against such a vessel (this is how a suspended vessel earns its way back into service). A schedule attempt that violates this rule is rejected with `ERR_VESSEL_NOT_INSPECTABLE`.

An inspector may not be double-booked. The assigned inspector must have no other non-cancelled inspection whose half-open window intersects the new one; because occupancy is half-open (see §2.5), a back-to-back booking where the previous inspection's `scheduled_end` equals this inspection's `scheduled_start` is permitted, but any true overlap is rejected with `ERR_INSPECTOR_DOUBLE_BOOKED`.

At scheduling time the system computes and stores the inspection's `provisional_fee_cents`, the PROVISIONAL variant of the certificate fee. This is an early estimate taken before any findings exist: it includes only the base class line and the pressure-tier line, with zero for the deficiency surcharge and zero for the incident surcharge. The full fee formula, shared with the FINAL variant, is specified in §3.7.

### 3.5. Recording Results and Raising Deficiencies

Before an inspection's result is recorded, the assigned `Inspector` may raise deficiencies against it. Raising is permitted only while the inspection is still `SCHEDULED`, otherwise it fails with `ERR_INVALID_STATE`; the caller is not required to be the inspection's assigned inspector (no ownership check is applied — any `Inspector` may raise). Raising a deficiency supplies its `severity` — either `CRITICAL` (which will bar a certificate and force the vessel out of service) or `NON_CRITICAL` (which merely restricts it) — and a `description` of what was found. A raised deficiency begins in `status` `OPEN`, takes its `vessel_id` from the originating inspection's vessel (denormalized for reverse lookup), and carries a null `repair_order_id`. Raising it increments the vessel's `open_deficiency_count` (and, when the severity is `CRITICAL`, its `open_critical_deficiency_count`) and recomputes the vessel's risk scores. Deficiencies may be listed — filterable by `inspection_id`, `vessel_id`, `repair_order_id`, `status`, or `severity` — or fetched individually.

Recording an inspection's result is performed by the assigned `Inspector` (the acting inspector's `id` must equal the inspection's `inspector_id`, else `ERR_OWNERSHIP_MISMATCH`), and it forks the inspection out of `SCHEDULED` based on the supplied `result`:

- **`result` of PASS** advances the inspection `SCHEDULED → PASSED`. It is permitted only when no deficiencies were attached to this inspection. It sets `result_recorded_at` to the clock now, recomputes the vessel's risk scores, and makes the vessel eligible for certificate issuance.
- **`result` of PASS_WITH_DEFICIENCIES** advances the inspection `SCHEDULED → PASSED_WITH_DEFICIENCIES`. It is permitted only when one or more `NON_CRITICAL` deficiencies are attached and zero `CRITICAL` deficiencies are attached. It sets `result_recorded_at` to the clock now; as a divergent side effect (contrasting with PASS) it moves a vessel that is `IN_SERVICE` to `RESTRICTED`; and it recomputes `open_deficiency_count` and the risk scores.
- **`result` of FAIL** advances the inspection `SCHEDULED → FAILED`. It is permitted only when one or more `CRITICAL` deficiencies are attached. It sets `result_recorded_at` to the clock now; as its divergent side effect it moves a vessel that is `IN_SERVICE` to `OUT_OF_SERVICE`; and it recomputes `open_critical_deficiency_count` and the risk scores.

Each of `PASSED`, `PASSED_WITH_DEFICIENCIES`, and `FAILED` is terminal for the inspection. Recording a result on an inspection that is not `SCHEDULED` fails with `ERR_INVALID_STATE`. An inspection may also reach the terminal `CANCELLED` state, either through a `JurisdictionAdmin` cancelling a `SCHEDULED` inspection directly or through the system's certificate-revocation cascade; a cancelled inspection is never billed a fee, and cancellation is permitted only from `SCHEDULED`.

The assigned `Inspector` also files the statutory **National Board report** for an inspection, supplying a `report_number` (the report form number, e.g. Form NB-6, unique across all reports) and a free-text `findings_summary`. The system stamps the report's `filed_by_inspector_id` from the filing inspector's `X-User-ID`. Filing is open to any `Inspector` (the caller need not be the inspection's assigned inspector — no ownership check) and is permitted regardless of the inspection's current status. A report links to its inspection through `inspection_id`. A duplicate `report_number` is rejected with `ERR_DUPLICATE_UNIQUE_FIELD`. Reports may be listed — filterable by `inspection_id` or `filed_by_inspector_id` — or fetched individually.

### 3.6. Repairing and Reinspecting Deficiencies

An `Owner` addresses open deficiencies by opening a **repair order** on one of its own vessels. The payload names the `vessel_id`, a list of `deficiency_ids` the order addresses, and a `description` of the repair scope. Every listed deficiency must belong to that `vessel_id` and must currently be `OPEN`; if any does not, the order is rejected with `ERR_DEFICIENCY_NOT_REPAIRABLE`. A new repair order begins in `status` `IN_PROGRESS`. As it is opened, each listed deficiency advances `OPEN → UNDER_REPAIR` and records the new order's id in its `repair_order_id`. Repair orders may be listed (filterable by `vessel_id` or `status`) or fetched individually.

Completing a repair order is an `Owner` operation restricted to the vessel's owner; it is permitted only while the order is `IN_PROGRESS`, and it advances the order `IN_PROGRESS → COMPLETED`. As its cascade, each deficiency linked to the order advances `UNDER_REPAIR → REINSPECTION`, and the vessel's risk scores are recomputed. Note that moving a deficiency into `REINSPECTION` leaves `open_deficiency_count` unchanged (the deficiency is still non-terminal), but it lowers `risk_score_standard` (which excludes reinspection work) while leaving `risk_score_forecast` unchanged (which still counts it) — the two scores are explained in §3.9. Cancelling a repair order (permitted only while `IN_PROGRESS`, and — unlike completion — not restricted to the vessel's owner, so any `Owner` may perform it) advances it `IN_PROGRESS → CANCELLED` and reverts each linked deficiency `UNDER_REPAIR → OPEN`, clearing that deficiency's `repair_order_id` so a fresh order may later be raised.

Reinspecting a deficiency is an `Inspector` operation carrying an `outcome`, and it is the enforcement point for **segregation of duties**: the acting inspector (`X-User-ID`) must not be the inspector of the deficiency's originating inspection, or the request is rejected with `ERR_SEGREGATION_OF_DUTIES`. A reinspection is permitted only when the deficiency is in `REINSPECTION`; otherwise it fails with `ERR_INVALID_STATE`. The `outcome` forks the deficiency:

- **`outcome` of PASS** advances the deficiency `REINSPECTION → CLEARED` (a terminal state). It decrements the vessel's `open_deficiency_count` (and its `open_critical_deficiency_count` when the deficiency is `CRITICAL`) and recomputes the risk scores. Critically, if this was the vessel's last non-terminal deficiency and the vessel is currently `RESTRICTED`, the vessel bubbles back up `RESTRICTED → IN_SERVICE` — this final-clear is the only path that returns a restricted vessel to service on its own.
- **`outcome` of FAIL** returns the deficiency `REINSPECTION → OPEN` (the cyclic edge). It clears the deficiency's `repair_order_id` back to null so the owner may raise a fresh repair order, and it recomputes the risk scores.

Separately, the inspector who originally raised a deficiency may **withdraw** it if it was raised in error. Withdrawal is permitted only while the deficiency is `OPEN` (otherwise it fails with `ERR_INVALID_STATE`), and only the raising inspector — the acting inspector's `id` must equal the originating inspection's `inspector_id` — may perform it (otherwise the request is rejected with `ERR_OWNERSHIP_MISMATCH`, which is checked before the `OPEN`-state check). Withdrawal advances the deficiency `OPEN → WITHDRAWN` (terminal), and as a compensating action for the original raise it decrements the vessel's `open_deficiency_count` (and `open_critical_deficiency_count` when the deficiency is `CRITICAL`) and recomputes the risk scores.

### 3.7. Fees, Certificate Issuance, Renewal, and Settlement

Once an inspection's result is recorded, a `JurisdictionAdmin` creates the **fee invoice** that bills that inspection's FINAL fee. The payload names the `vessel_id` and the `inspection_id`. Invoice creation does not itself enforce that the inspection already carries a recorded result — the FINAL fee is simply computed from the inspection's current `is_special` flag and its attached non-withdrawn `NON_CRITICAL` deficiency count. The invoice's `amount_cents` is computed via the FINAL fee variant; it begins in `status` `UNPAID` with `amount_paid_cents` and `refunded_cents` both zero and a null `certificate_id`. Fee invoices may be listed — filterable by `vessel_id`, `inspection_id`, `certificate_id`, or `status` — or fetched individually.

**The certificate fee formula.** The fee is built from up to four line items, in this fixed order. The first line is the base fee for the vessel's class: 20000 cents for a `POWER_BOILER`, 10000 cents for a `HEATING_BOILER`, and 15000 cents for a `PRESSURE_VESSEL`. The second line is the pressure-tier fee determined by the vessel's `mawp_psig`: zero when the pressure is at most 15 psig; 4500 cents when the pressure is above 15 and at most 150; 12000 cents when above 150 and at most 600; and 25000 cents when above 600. The third line is a deficiency surcharge of 2500 cents multiplied by the number of `NON_CRITICAL` deficiencies attached to the inspection whose status is not `WITHDRAWN`. The fourth line is a flat incident surcharge of 30000 cents, applied only when the inspection's `is_special` flag is true. The PROVISIONAL variant, computed at scheduling, uses only the first two lines and sets the third and fourth to zero; the FINAL variant, computed at invoice creation using the actual non-withdrawn `NON_CRITICAL` deficiency count and the recorded `is_special` flag, adds the third and fourth lines, so the two variants diverge exactly when deficiencies were found or the inspection is special. Each non-zero line is first multiplied by one plus the jurisdiction's `admin_fee_pct` (which defaults to 0.075) and rounded to whole cents using round-half-up; the rounded lines are then summed to produce the fee. Rounding is per line, then summed — never sum-then-round.

An `Owner` pays a fee invoice billed against its own vessel. Payment is permitted only while the invoice is `UNPAID`; it advances the invoice `UNPAID → PAID`, sets `amount_paid_cents` equal to `amount_cents`, and credits the jurisdiction's `collected_fees_cents` ledger by `amount_cents`. A `JurisdictionAdmin` may void an `UNPAID` invoice raised in error, advancing it `UNPAID → VOID` (terminal) with no ledger effect. A `JurisdictionAdmin` may also refund a `PAID` invoice, but only once no `ACTIVE` certificate references it — the referencing certificate must first become `REVOKED`, `SUPERSEDED`, or `EXPIRED`, and a refund attempted while an `ACTIVE` certificate still references the invoice is rejected with `ERR_INVALID_STATE`; refunding advances the invoice `PAID → REFUNDED` (terminal), sets `refunded_cents` equal to `amount_cents`, and debits the jurisdiction's `collected_fees_cents` by `amount_cents`, so the pay-then-refund pair nets to zero. Any of these transitions attempted from a disallowed state fails with `ERR_INVALID_STATE`.

**Issuing a certificate** is a `JurisdictionAdmin` operation and the convergence point of the whole workflow. The payload names the `vessel_id`, the passing `inspection_id`, the `fee_invoice_id` covering it, the required `expected_vessel_version` (see §2.6), and an optional `supersedes_certificate_id` for renewals. Several preconditions guard issuance, and each carries its own error: the referenced inspection must be in `PASSED` or `PASSED_WITH_DEFICIENCIES`, else `ERR_INVALID_STATE`; `expected_vessel_version` must match the vessel's current `version`, else `ERR_STALE_VESSEL_VERSION` (412); the vessel must have no non-terminal `CRITICAL` deficiency (`open_critical_deficiency_count` must be zero), else `ERR_CRITICAL_DEFICIENCY_OPEN`; and the referenced fee invoice must be `PAID` with its `vessel_id` and `inspection_id` matching those on the request, else `ERR_FEE_NOT_PAID` (402). A new certificate begins in `status` `ACTIVE`. On issuance the system computes the validity window (below), links the invoice by setting its `certificate_id` and sets the vessel's `current_certificate_id` to the new certificate, and increments the vessel's `version` by 1. When the certificate is a first issuance against a `NOT_IN_SERVICE` vessel that rests on a `PASSED` inspection with `open_critical_deficiency_count` at zero, the vessel's `service_status` advances `NOT_IN_SERVICE → IN_SERVICE` and its risk scores are recomputed. When `supersedes_certificate_id` is supplied and points at that vessel's current `ACTIVE` certificate (a renewal), the prior certificate advances `ACTIVE → SUPERSEDED` and the newly issued `ACTIVE` certificate becomes the vessel's `current_certificate_id`. The only validation applied to a supplied `supersedes_certificate_id` is that the referenced certificate exists (`ERR_NOT_FOUND` otherwise) and is `ACTIVE` (`ERR_INVALID_STATE` otherwise); the server does not verify that it belongs to this vessel or that it is the vessel's current certificate. Certificates may be listed — filterable by `vessel_id`, `inspection_id`, `fee_invoice_id`, `supersedes_certificate_id`, or `status` — or fetched individually.

**The validity window.** On issuance, `valid_from` is set to the clock now (inclusive). The interval in months is the jurisdiction's `interval_months_override` when that override is not null; otherwise it is the class default — 12 months for a `POWER_BOILER`, 12 months for a `HEATING_BOILER`, and 24 months for a `PRESSURE_VESSEL`. Then `valid_until` is `valid_from` advanced by that many calendar months, keeping the same day-of-month. A vessel is OVERDUE, and its certificate expirable, exactly when the clock now is at or after `valid_until` (the boundary instant itself counts as due).

A `JurisdictionAdmin` may **expire** an `ACTIVE` certificate, advancing it `ACTIVE → EXPIRED`, but only when the clock now has reached `valid_until` (at or after that instant); an expire attempted before the certificate is due is rejected with `ERR_CERTIFICATE_NOT_DUE`. Expiry clears the vessel's `current_certificate_id`. A `JurisdictionAdmin` may also **revoke** an `ACTIVE` certificate, advancing it `ACTIVE → REVOKED`; revocation cascades by cancelling the vessel's `SCHEDULED` non-`SPECIAL` inspections (each moving `SCHEDULED → CANCELLED`) and clearing the vessel's `current_certificate_id`. Both `EXPIRED` and `REVOKED`, along with `SUPERSEDED`, are terminal certificate states, and either transition attempted on a non-`ACTIVE` certificate fails with `ERR_INVALID_STATE`.

### 3.8. Incidents, Emergency Cascades, and Reinstatement

An incident report may be filed against a vessel by either its `Owner` or a `JurisdictionAdmin`. The payload names the `severity` (either `MINOR` or `CRITICAL`), the `occurred_at` instant, and a `narrative` describing what happened. A `MINOR` incident is recorded for the risk history but drives no state change. A `CRITICAL` incident, however, is an emergency and triggers a coordinated cascade, provided the vessel's `service_status` is `IN_SERVICE` or `RESTRICTED`:

1. The vessel's `service_status` advances to `SUSPENDED`.
2. Any `ACTIVE` certificate on the vessel is revoked (`ACTIVE → REVOKED`), which in turn cancels the vessel's `SCHEDULED` non-`SPECIAL` inspections and clears `current_certificate_id`, exactly as an ordinary revocation would.
3. After that revoke cascade has run, the system auto-creates a new `SPECIAL` inspection in `SCHEDULED` (this new special inspection is deliberately not swept up by the cancellation) and records its id on the incident's `triggered_inspection_id`. This auto-created inspection carries a null `inspector_id`, both `scheduled_start` and `scheduled_end` set to the clock now, `is_special` true, a null `result_recorded_at`, and a `provisional_fee_cents` computed from the base-class and pressure-tier lines only (the same PROVISIONAL variant used at ordinary scheduling).
4. The vessel's risk scores are recomputed (a `SUSPENDED` vessel carries an added penalty) and the vessel's `version` is incremented by 1.

Incident reports may be listed — filterable by `vessel_id`, `triggered_inspection_id`, or `severity` — or fetched individually.

A suspended vessel earns its way back through that auto-created special inspection. Once the vessel's `SPECIAL` inspection has been recorded as `PASSED` and the vessel's `open_critical_deficiency_count` is zero, a `JurisdictionAdmin` may **reinstate** the vessel, advancing its `service_status` `SUSPENDED → IN_SERVICE`, recomputing its risk scores, and incrementing its `version` by 1. Reinstatement attempted before those conditions hold fails with `ERR_INVALID_STATE`.

### 3.9. The Two Risk Scores

Every vessel carries two derived risk scores, both integers clamped to the range 0 through 100, and both recomputed after any inspection result, any deficiency status change, any incident filing, and any reinstatement. They differ in exactly one respect: which deficiencies they count.

The computation begins from a class base — 30 for a `POWER_BOILER`, 15 for a `HEATING_BOILER`, and 20 for a `PRESSURE_VESSEL`. To this is added an age factor derived from the vessel's `installed_at`: the vessel's age in whole years is the number of days from `installed_at` to the clock now divided by 365 and rounded down. The age factor is 0 when the vessel is younger than 5 years, 10 when it is at least 5 but under 15 years, 20 when it is at least 15 but under 30 years, and 35 when it is 30 years or older. Next comes the deficiency weight: each counted `CRITICAL` deficiency contributes 8 and each counted `NON_CRITICAL` deficiency contributes 3. An incident penalty of 25 is added for each incident report on the vessel whose `occurred_at` falls within the trailing 365 days of the clock now. A clean bonus of 10 is subtracted when the vessel's most recent terminal inspection is `PASSED` with zero attached deficiencies (otherwise no bonus applies); here "most recent terminal inspection" means the inspection with the latest `result_recorded_at` (i.e. one of `PASSED`, `PASSED_WITH_DEFICIENCIES`, or `FAILED`; `CANCELLED` inspections record no result and are ignored, ties broken by creation order), and "zero attached deficiencies" counts every deficiency linked to that inspection regardless of status (including `WITHDRAWN`). If the vessel's `service_status` is `SUSPENDED`, a further penalty of 40 is added. The running total — base plus age factor plus deficiency weight plus incident penalty, minus the clean bonus, plus the suspended penalty where applicable — is then clamped so that anything below 0 becomes 0 and anything above 100 becomes 100, yielding the stored integer.

The only difference between the two variants is the set of deficiencies included in the deficiency weight. The **STANDARD** score, stored in `risk_score_standard`, counts only deficiencies in `OPEN` or `UNDER_REPAIR` and excludes those in `REINSPECTION` — it reflects currently-realized open work. The **FORECAST** score, stored in `risk_score_forecast`, counts deficiencies in `OPEN`, `UNDER_REPAIR`, and `REINSPECTION` at full weight — it is the forward-looking view, so a vessel mid-reinspection scores higher under FORECAST than under STANDARD. This is why completing a repair order (which moves deficiencies into `REINSPECTION`) drops the standard score while leaving the forecast score unchanged.

## 4. Endpoint Definitions

All endpoints share the response envelope of §2.2. Creating a new resource returns HTTP 201; a successful read or an operation that only modifies existing state returns HTTP 200. Request bodies, computed side effects, and validation conditions are not repeated here — reconstruct them from the §3 narratives.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/_clock/set_current_utc` | Set the server logical clock. | JurisdictionAdmin |
| POST | `/jurisdictions` | Create a jurisdiction. | JurisdictionAdmin |
| GET | `/jurisdictions` | List jurisdictions. | JurisdictionAdmin, Owner, Inspector |
| GET | `/jurisdictions/{jurisdictionId}` | Fetch a jurisdiction. | JurisdictionAdmin, Owner, Inspector |
| POST | `/insurance-companies` | Create an insurance company. | JurisdictionAdmin |
| GET | `/insurance-companies` | List insurance companies. | JurisdictionAdmin, Owner, Inspector |
| GET | `/insurance-companies/{insuranceCompanyId}` | Fetch an insurance company. | JurisdictionAdmin, Owner, Inspector |
| POST | `/owners` | Create an owner. | JurisdictionAdmin |
| GET | `/owners` | List owners. | JurisdictionAdmin, Owner, Inspector |
| GET | `/owners/{ownerId}` | Fetch an owner. | JurisdictionAdmin, Owner, Inspector |
| POST | `/inspectors` | Register an inspector (starts PENDING). | JurisdictionAdmin |
| GET | `/inspectors` | List inspectors. | JurisdictionAdmin, Owner, Inspector |
| GET | `/inspectors/{inspectorId}` | Fetch an inspector. | JurisdictionAdmin, Owner, Inspector |
| POST | `/inspectors/{inspectorId}/commission` | Commission or re-commission an inspector. | JurisdictionAdmin |
| POST | `/inspectors/{inspectorId}/suspend` | Suspend a commissioned inspector. | JurisdictionAdmin |
| POST | `/vessels` | Register a vessel in DRAFT. | Owner |
| GET | `/vessels` | List vessels. | JurisdictionAdmin, Owner, Inspector |
| GET | `/vessels/{vesselId}` | Fetch a vessel. | JurisdictionAdmin, Owner, Inspector |
| POST | `/vessels/{vesselId}/register` | Register a vessel (DRAFT → REGISTERED). | JurisdictionAdmin |
| POST | `/vessels/{vesselId}/retire` | Retire a vessel (REGISTERED → RETIRED). | JurisdictionAdmin |
| POST | `/vessels/{vesselId}/reinstate` | Reinstate a suspended vessel to service. | JurisdictionAdmin |
| POST | `/vessels/{vesselId}/incidents` | File an incident report against a vessel. | Owner, JurisdictionAdmin |
| POST | `/insurance-policies` | Record an insurance policy. | JurisdictionAdmin |
| GET | `/insurance-policies` | List insurance policies. | JurisdictionAdmin, Owner, Inspector |
| GET | `/insurance-policies/{policyId}` | Fetch an insurance policy. | JurisdictionAdmin, Owner, Inspector |
| POST | `/insurance-policies/{policyId}/cancel` | Cancel an active policy. | JurisdictionAdmin |
| POST | `/insurance-policies/{policyId}/expire` | Expire an active policy past coverage. | JurisdictionAdmin |
| POST | `/inspections` | Schedule an inspection. | JurisdictionAdmin |
| GET | `/inspections` | List inspections. | JurisdictionAdmin, Owner, Inspector |
| GET | `/inspections/{inspectionId}` | Fetch an inspection. | JurisdictionAdmin, Owner, Inspector |
| POST | `/inspections/{inspectionId}/result` | Record the inspection result. | Inspector |
| POST | `/inspections/{inspectionId}/deficiencies` | Raise a deficiency against an inspection. | Inspector |
| POST | `/inspections/{inspectionId}/national-board-report` | File the National Board report. | Inspector |
| POST | `/inspections/{inspectionId}/cancel` | Cancel a scheduled inspection. | JurisdictionAdmin |
| GET | `/national-board-reports` | List National Board reports. | JurisdictionAdmin, Owner, Inspector |
| GET | `/national-board-reports/{reportId}` | Fetch a National Board report. | JurisdictionAdmin, Owner, Inspector |
| GET | `/deficiencies` | List deficiencies. | JurisdictionAdmin, Owner, Inspector |
| GET | `/deficiencies/{deficiencyId}` | Fetch a deficiency. | JurisdictionAdmin, Owner, Inspector |
| POST | `/deficiencies/{deficiencyId}/reinspect` | Reinspect a deficiency (PASS/FAIL). | Inspector |
| POST | `/deficiencies/{deficiencyId}/withdraw` | Withdraw an OPEN deficiency raised in error. | Inspector |
| POST | `/repair-orders` | Open a repair order on OPEN deficiencies. | Owner |
| GET | `/repair-orders` | List repair orders. | JurisdictionAdmin, Owner, Inspector |
| GET | `/repair-orders/{repairOrderId}` | Fetch a repair order. | JurisdictionAdmin, Owner, Inspector |
| POST | `/repair-orders/{repairOrderId}/complete` | Complete a repair order. | Owner |
| POST | `/repair-orders/{repairOrderId}/cancel` | Cancel a repair order. | Owner |
| POST | `/fee-invoices` | Create the FINAL fee invoice. | JurisdictionAdmin |
| GET | `/fee-invoices` | List fee invoices. | JurisdictionAdmin, Owner, Inspector |
| GET | `/fee-invoices/{feeInvoiceId}` | Fetch a fee invoice. | JurisdictionAdmin, Owner, Inspector |
| POST | `/fee-invoices/{feeInvoiceId}/pay` | Pay a fee invoice. | Owner |
| POST | `/fee-invoices/{feeInvoiceId}/refund` | Refund a paid fee invoice. | JurisdictionAdmin |
| POST | `/fee-invoices/{feeInvoiceId}/void` | Void an unpaid fee invoice. | JurisdictionAdmin |
| POST | `/certificates` | Issue or renew a certificate. | JurisdictionAdmin |
| GET | `/certificates` | List certificates. | JurisdictionAdmin, Owner, Inspector |
| GET | `/certificates/{certificateId}` | Fetch a certificate. | JurisdictionAdmin, Owner, Inspector |
| POST | `/certificates/{certificateId}/revoke` | Revoke an active certificate. | JurisdictionAdmin |
| POST | `/certificates/{certificateId}/expire` | Expire an active certificate once due. | JurisdictionAdmin |
| GET | `/incidents` | List incident reports. | JurisdictionAdmin, Owner, Inspector |
| GET | `/incidents/{incidentId}` | Fetch an incident report. | JurisdictionAdmin, Owner, Inspector |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| --- | --- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_OWNERSHIP_MISMATCH` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_VESSEL_VERSION` | 412 |
| `ERR_VESSEL_NOT_INSPECTABLE` | 409 |
| `ERR_CRITICAL_DEFICIENCY_OPEN` | 409 |
| `ERR_INSURANCE_COORDINATION_INVALID` | 409 |
| `ERR_INSPECTOR_NOT_COMMISSIONED` | 409 |
| `ERR_SEGREGATION_OF_DUTIES` | 409 |
| `ERR_DUPLICATE_UNIQUE_FIELD` | 409 |
| `ERR_DEFICIENCY_NOT_REPAIRABLE` | 409 |
| `ERR_INSPECTOR_DOUBLE_BOOKED` | 409 |
| `ERR_POLICY_COVERAGE_OVERLAP` | 409 |
| `ERR_FEE_NOT_PAID` | 402 |
| `ERR_CERTIFICATE_NOT_DUE` | 409 |
| `ERR_POLICY_NOT_EXPIRABLE` | 409 |
| `ERR_INVALID_REQUEST` | 400 |
