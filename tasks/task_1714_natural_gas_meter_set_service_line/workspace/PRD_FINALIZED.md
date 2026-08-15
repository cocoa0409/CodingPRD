# Natural Gas Meter Set API — Product Requirements Document

## 1. Introduction

A gas utility's new-business group shepherds every residential and commercial new-service request through a long, heavily regulated journey: a builder files a service application, engineers size the connected gas load and design the main extension, billing collects a contribution in aid of construction, coordinators secure road-cut and crossing permits, field crews build the service line, meter technicians set and test the meter, inspectors witness the safety evidence, and only then is gas turned on and the as-built geometry committed to the utility's GIS. Each hand-off carries money, safety evidence, or a regulatory deadline, and a mistake in any of them surfaces weeks later as a billing dispute, a failed inspection, or a missed in-service commitment.

This document specifies an API that runs that journey as a single, state-driven workflow. A **Service Application** advances along a canonical spine of statuses while child resources — appliance loads, the main-extension design, the CIAC invoice, permits, crew bookings, inspections, the meter set, purge and leak tests, turn-on events, the timeline commitment, and the GIS as-built — each follow their own lifecycles and, at defined moments, push the spine forward or hold it back. The system enforces segregation of duties between the people who issue money documents and the people who collect them, between the technician who performs a leak test and the inspector who certifies it, and between optimistic and conservative schedule commitments. All money moves in integer cents, all safety thresholds are exact, and a logical clock drives every time-based expiry so that the passage of time itself is a testable input.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, principles, and boilerplate that apply to the entire API. All resource collections are mounted directly under the API root — there are no nested URL hierarchies; resources reference one another through identifier fields in their payloads.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the caller's operational capacity. A request missing either header, or carrying a role string the system does not recognize, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is not on the target endpoint's authorized-role list is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403).

Ten roles are recognized, spelled exactly as follows: `Builder`, `NewBusinessRep`, `DesignEngineer`, `BillingClerk`, `PermitCoordinator`, `FieldSupervisor`, `MeterTechnician`, `Inspector`, `GISAnalyst`, and `SystemAdmin`.

Two roles are entity-backed. When `X-User-Role` is `Builder`, `X-User-ID` is the `id` of the acting Builder account; ownership checks on any resource that references a builder compare the resource's `builder_id` field to `X-User-ID`, and a mismatch is rejected with `ERR_FORBIDDEN_OWNER` (HTTP 403). When `X-User-Role` is `Inspector`, `X-User-ID` is the `id` of the acting Inspector record; recording an inspection result compares the inspection's `inspector_id` to `X-User-ID`, again rejecting a mismatch with `ERR_FORBIDDEN_OWNER`. The remaining roles — `NewBusinessRep`, `DesignEngineer`, `BillingClerk`, `PermitCoordinator`, `FieldSupervisor`, `MeterTechnician`, `GISAnalyst`, and `SystemAdmin` — are opaque: their `X-User-ID` is an operator identifier not tied to any persisted entity. The server may record it (for example, as `issued_by_user_id` on an invoice, `recorded_by_user_id` on a payment event, `installed_by_user_id` on a meter set, `submitted_by_user_id` on a GIS record, or `validated_by_user_id` on a validated as-built) but never compares it to an entity's `id`.

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

List endpoints accept two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter skips a number of items from the start of the result set and defaults to 0. Unless otherwise specified, every list endpoint returns its resources sorted by `created_at` in ascending order. List responses carry the pagination fields `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. Common Resource Properties

Every primary resource carries a standard set of system-managed fields:

- `id` (string): a server-minted UUID with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits, set at creation.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation.
- `version` (integer): starts as a small integer and increments by one on every mutation of the resource — including system-driven mutations caused by cascades from other resources, not just direct client writes.

One resource is deliberately exempt: a **CIAC payment event** is an append-only ledger entry. It carries `id` and `created_at` only — both `updated_at` and `version` are absent, because a payment or refund event, once recorded, is never modified.

### 2.5. The Application Spine and the Parallel Hold Axis

A service application's `status` walks a canonical spine, in this exact order: `DRAFT`, `SUBMITTED`, `LOAD_CONFIRMED`, `DESIGN`, `QUOTED`, `CIAC_PENDING`, `APPROVED_FOR_CONSTRUCTION`, `PERMITTING`, `CONSTRUCTION_SCHEDULED`, `SERVICE_INSTALLED`, `METER_WORK`, `TESTING`, `TURN_ON`, `ENERGIZED`, `GIS_REVIEW`, and finally `COMPLETED`. Three further statuses — `REJECTED`, `CANCELLED`, and `EXPIRED` — are terminal outcomes that sit off the spine. Whenever this document says a guard requires the spine to be "at SERVICE_INSTALLED or later", the phrase refers to this ordering. `COMPLETED`, `REJECTED`, `CANCELLED`, and `EXPIRED` are the application's terminal states; once an application is terminal, every mutation targeting it or any of its children is rejected with `ERR_APPLICATION_TERMINAL` (HTTP 409).

Independent of the spine, an application carries a parallel hold axis in its `hold_status`, one of `NOT_HELD`, `HELD_BY_BUILDER`, or `HELD_BY_UTILITY`, defaulting to `NOT_HELD`. A hold never changes the spine status, but any `hold_status` other than `NOT_HELD` freezes the application: every child-entity mutation and every spine transition is rejected with `ERR_APPLICATION_ON_HOLD` (HTTP 409) until the hold is cleared.

### 2.6. Order of Validation Evaluation

When several checks could reject the same request, the server evaluates them in a fixed order so that the surfaced error is deterministic:

1. **Authentication** — the headers are present and name a declared role, else `ERR_UNAUTHENTICATED`.
2. **Role authorization** — the acting role is on the endpoint's authorized list, else `ERR_UNAUTHORIZED_ROLE`.
3. **Ownership** — a `Builder` actor's `X-User-ID` matches the resource's `builder_id`, and an `Inspector` actor's `X-User-ID` matches the inspection's `inspector_id` when recording a result, else `ERR_FORBIDDEN_OWNER`. This check governs the builder-scoped mutations: submitting an application, holding, resuming, or cancelling it, writing appliance loads, accepting a quote, and accepting or proposing revisions on a commitment — plus inspection result recording.
4. **Existence** — path identifiers and body foreign-key references are resolved left to right, path parameters first and then body fields in their declared order; the first unresolved reference produces that entity's own 404 error (see §2.10).
5. **Optimistic concurrency** — any `expected_..._version` field in the body is compared to the target entity's current `version`, else `ERR_STALE_VERSION` (HTTP 412).
6. **Application posture** — a terminal spine status rejects the mutation with `ERR_APPLICATION_TERMINAL`; a non-`NOT_HELD` hold status rejects it with `ERR_APPLICATION_ON_HOLD`. The terminal check precedes the hold check.
7. **Entity state machine validity** — the target entity's current state must permit the requested transition, else `ERR_INVALID_STATE` or the more specific member of the state-gate family (`ERR_INVOICE_NOT_PAYABLE`, `ERR_INVOICE_NOT_REFUNDABLE`, `ERR_COMMITMENT_NOT_REVISABLE`, `ERR_SERVICE_LINE_NOT_INSTALLED`, `ERR_METER_NOT_READY`), all HTTP 409.
8. **Safety and segregation-of-duties rules** — purge and leak test parameters, witness/installer, payer/issuer, and refund/payer separation, and the GIS cover-depth rule; these guard documenting a purge and leak test, witness-certifying one, recording a CIAC payment, recording a CIAC refund, and validating a GIS as-built.
9. **Temporal rules** — quote freshness and not-in-the-past date checks (`ERR_QUOTE_EXPIRED`, `ERR_DATE_IN_PAST`), guarding quote acceptance, crew-booking confirmation, inspection creation, inspection rescheduling, commitment revision proposals, and permit decision recording.
10. **Business constraints** — uniqueness of one non-`CANCELLED` main extension, meter set, GIS record, and timeline commitment per application; locked loads (`ERR_LOADS_LOCKED`); a single active leak test per meter set (`ERR_TEST_ALREADY_ACTIVE`); inspector certification coverage (`ERR_INSPECTOR_NOT_CERTIFIED`); crew and inspector window conflicts; crew daily capacity; meter size availability; builder standing; presence of at least one load; and the bar on revising a design whose invoice has payments.
11. **Cross-entity referential gates** — permit readiness, confirmed bookings, verified turn-ons, validated GIS records, and load/application matching, guarding construction scheduling, energization, completion, and turn-on creation.
12. **Fiscal gates** — CIAC settlement state and payment/refund amount rules (`ERR_CIAC_UNPAID`, `ERR_OVERPAYMENT`, `ERR_REFUND_AMOUNT_MISMATCH`), guarding construction scheduling, application completion, payment recording, and refund recording.

Separately from this ordered stack, malformed request bodies — a missing required field, a value of the wrong type, an enum member outside the declared set, a non-positive quantity, footage, or money amount, a time window whose end does not fall strictly after its start, or a road-cut permit with an empty crossing list — are rejected with `ERR_INVALID_REQUEST` (HTTP 400).

### 2.7. Optimistic Concurrency Control

Three write operations require the caller to prove it has observed the current state of the entity it is modifying. Editing an appliance load requires the body to carry `expected_load_version` equal to that load's current `version`. Editing a draft application's header requires `expected_application_version` equal to the application's current `version`. Proposing a commitment revision requires `expected_commitment_version` equal to the commitment's current `version` — and this check applies even when the commitment has since returned to `ACCEPTED` after an earlier propose-then-reject round trip, because that round trip restored the state but advanced the version. In all three cases, if the supplied value does not match the entity's current `version` — because another writer has advanced it since the client last read the entity — the request is rejected with `ERR_STALE_VERSION` (HTTP 412) rather than overwriting state the client never observed. A fourth operation follows the same pattern for its own entity: sending a quoted main-extension design back to draft requires `expected_main_extension_version` to match the main extension's current `version`, with the same `ERR_STALE_VERSION` (HTTP 412) on mismatch. Endpoints not named here do not accept a version field.

### 2.8. Money, Measurement Precision, and Rounding

All monetary values are integer cents — never fractional, never floating point. Gas-load figures are carried at one decimal place, and pressure-drop figures at three decimal places. Wherever a calculation in this document rounds, it rounds half up at the stated precision, and the rounding step is part of the contract: calculations that pin a rounding order (the per-segment road-cut fee is the notable one) must be evaluated in exactly the order described. Dates used in schedule commitments are whole ISO calendar dates, and all date arithmetic is calendar-day arithmetic.

### 2.9. The Logical Clock and Scheduled Sweeps

The system keeps a logical clock that governs every date comparison in this document; it never falls back to wall-clock time. Before any administrator has set it, the logical clock reads exactly `2026-08-01T00:00:00Z`. A `SystemAdmin` moves time forward through an admin-only clock-setting capability whose request carries a `to_iso8601` instant and whose response reports the resulting `current_utc`. Each successful set atomically runs all four time-based sweeps:

- **Quote expiry** — an application still `QUOTED` whose current date has moved more than seven days past its `quote_valid_until` is swept to `EXPIRED`, with the compensation cascade described in §3.9. During the seven-day grace window itself the application remains `QUOTED`, but quote acceptance already fails with `ERR_QUOTE_EXPIRED`.
- **Permit expiry** — a permit in `APPROVED` whose `expires_at` date has passed moves to `EXPIRED`.
- **Inspection expiry** — an inspection still `SCHEDULED` whose `inspection_date` has passed moves to `EXPIRED`.
- **Commitment sweep** — a timeline commitment in `ACCEPTED` or `AT_RISK` whose `committed_completion_date` has passed, while its application is not yet `COMPLETED`, moves to `MISSED`; a commitment swept from `ACCEPTED` that has no recorded delay attribution is attributed to `UTILITY` by default.

### 2.10. Existence Checks and Per-Entity Not-Found Errors

References are resolved in a fixed left-to-right order: path identifiers first, then body foreign-key fields in their declared order. The first unresolved reference aborts the request with the 404 specific to that entity, and every entity family has its own: `ERR_BUILDER_NOT_FOUND`, `ERR_APPLICATION_NOT_FOUND`, `ERR_LOAD_NOT_FOUND`, `ERR_MAIN_EXTENSION_NOT_FOUND`, `ERR_INVOICE_NOT_FOUND`, `ERR_PAYMENT_NOT_FOUND`, `ERR_PERMIT_NOT_FOUND`, `ERR_CREW_NOT_FOUND`, `ERR_BOOKING_NOT_FOUND`, `ERR_INSPECTOR_NOT_FOUND`, `ERR_INSPECTION_NOT_FOUND`, `ERR_METER_SET_NOT_FOUND`, `ERR_TEST_NOT_FOUND`, `ERR_TURN_ON_NOT_FOUND`, `ERR_COMMITMENT_NOT_FOUND`, and `ERR_GIS_NOT_FOUND`. A request naming both a non-existent application in the body and a non-existent invoice in the path therefore surfaces `ERR_INVOICE_NOT_FOUND`, because the path is validated before the body.

## 3. Business Logic & Workflows

### 3.1. Builders, Service Applications, and the Connected Load

Everything begins with a builder account. A `NewBusinessRep` or a `SystemAdmin` registers a builder with its `company_name`, `contact_email`, and `license_number`; the account starts in `ACTIVE` status. A `SystemAdmin` may later suspend or reactivate a builder by updating its `status` to `SUSPENDED` or back to `ACTIVE`. A suspended builder cannot open new applications and cannot submit draft ones: both attempts are rejected with `ERR_BUILDER_SUSPENDED` (HTTP 422).

A `Builder` opens a new-service application by naming its own `builder_id` together with the `service_address`, `city`, `state_code`, and `postal_code` of the site, the `requested_in_service_date` it wants gas on, and an optional `pressure_class_requested` — `LOW` for standard 0.25 psi delivery or `MEDIUM` for 2 psi delivery, defaulting to `LOW` when omitted. The application starts in `DRAFT`. While it remains a draft, the owning builder may patch the header fields `service_address`, `city`, `state_code`, `postal_code`, and `requested_in_service_date`; editing anything after the draft stage is rejected with `ERR_INVALID_STATE`.

The builder then declares what will burn gas. Each appliance load row carries the application's `service_application_id`, an `appliance_type` drawn from `FURNACE`, `WATER_HEATER`, `RANGE`, `DRYER`, `FIREPLACE`, `STANDBY_GENERATOR`, `POOL_HEATER`, or `OTHER`, a `quantity` of at least one, and a per-unit nameplate `btuh_input_rating` greater than zero. The system computes each row's `counted_load_cfph`: the quantity multiplied by the nameplate rating, divided by one thousand BTU per hour per cubic foot per hour, rounded half up to one decimal place — and recomputes that figure whenever the row is created or edited. Rows may be added while the application is `DRAFT` or `SUBMITTED`; editing and deleting individual rows is permitted only while the application is `DRAFT`. Once the application reaches `LOAD_CONFIRMED`, every load write — create, edit, or delete — is rejected with `ERR_LOADS_LOCKED` (HTTP 409).

Submission is the builder's declaration that the load sheet is complete. Submitting requires that the acting builder own the application (`ERR_FORBIDDEN_OWNER`), that the builder still be `ACTIVE`, and that at least one appliance load row exist — an empty load sheet is rejected with `ERR_NO_APPLIANCE_LOADS` (HTTP 422). A successful submission moves the application from `DRAFT` to `SUBMITTED`, stamps `submitted_at`, and runs the load calculation, persisting three computed figures on the application. `appliance_count` is the number of load rows (not the sum of their quantities). `total_connected_load_cfph` is the sum of every row's `counted_load_cfph`, rounded half up to one decimal place. `diversity_adjusted_load_cfph` applies a coincidence factor that depends only on the row count: exactly one row keeps the full connected load (factor 1.00); two or three rows take 0.85; four, five, or six rows take 0.75; seven or more rows take 0.65 — the connected load multiplied by the applicable factor, again rounded half up to one decimal place.

A `NewBusinessRep` then reviews the numbers. Confirming the load moves the application from `SUBMITTED` to `LOAD_CONFIRMED` and freezes the load rows for the rest of the journey; rejecting the application (with a free-text `reason`) moves it from `SUBMITTED` to the terminal `REJECTED` state.

At any point, any authenticated role can read the application's computed posture: a readiness view reporting `readiness_posture` (`READY` when there is nothing outstanding, `BLOCKED` the moment any blocker exists), a `blockers` list whose entries come from the fixed vocabulary `CIAC_UNPAID`, `PERMIT_NOT_APPROVED`, `NO_CONFIRMED_BOOKING`, `METER_NOT_READY`, `TURN_ON_INCOMPLETE`, `GIS_NOT_VALIDATED`, and `ON_HOLD`, plus live counters derived from the child rows: `unpaid_ciac_cents`, `open_permit_count`, `confirmed_booking_count`, `verified_turn_on_count`, `active_load_count`, and the boolean `gis_validated`. Every blocker is computed from current state at whatever spine stage the application happens to occupy — the view is a global checklist, not a stage-gated one, so a downstream blocker appears whenever its condition fails, regardless of whether that work has begun. The conditions are evaluated in this order: `ON_HOLD` whenever the application's `hold_status` is other than `NOT_HELD`; `CIAC_UNPAID` whenever no CIAC invoice exists for the application or the invoice's status is other than `PAID`, `SETTLED`, `REFUNDED`, or `VOID`; `PERMIT_NOT_APPROVED` whenever any permit of the application sits in a status other than `APPROVED` or `CLOSED`, and also — when a non-`CANCELLED` main extension with `crossings_count` greater than zero exists — whenever no `ROAD_CUT` permit of the application is `APPROVED` or `CLOSED`; `NO_CONFIRMED_BOOKING` whenever no booking of the application is `CONFIRMED`; `METER_NOT_READY` whenever no non-`CANCELLED` meter set exists or the meter set's status is other than `READY_FOR_TURN_ON` — including after the set has advanced to `ENERGIZED`; `TURN_ON_INCOMPLETE` whenever any appliance load of the application lacks a `VERIFIED` turn-on event; and `GIS_NOT_VALIDATED` whenever no `VALIDATED` GIS as-built exists. Each vocabulary entry appears at most once in the list, in the order the conditions are listed.

### 3.2. Main-Extension Design, Provisional CIAC, and the Quote

Once the load is confirmed, a `DesignEngineer` authors the main-extension design: the `service_application_id` it belongs to, a `design_footage_ft` greater than zero, a `crossings` list of road-crossing segments (each segment naming a `surface_type` of `ASPHALT`, `CONCRETE`, or `LANDSCAPE` plus its `length_ft` and `width_ft`; the list may be empty), and an optional `rock_excavation_expected` flag defaulting to false. Creating the design moves its application from `LOAD_CONFIRMED` to `DESIGN`. An application carries at most one non-`CANCELLED` main extension; a second attempt is rejected with `ERR_DUPLICATE_MAIN_EXTENSION` (HTTP 409).

Design creation immediately prices the provisional contribution in aid of construction, in a pinned evaluation order. First, the tariff allowance `allowance_ft` is one hundred feet plus twenty-five feet for each appliance row on the application. Second, the `provisional_base_cost_cents` is the design footage priced at the standard unit cost of 4,500 cents per foot ($45.00). Third, the `provisional_surcharges_cents` is 15,000 cents ($150.00) for every crossing segment — the derived `crossings_count` — plus, only when rock excavation is expected, 2,000 cents per design foot. Fourth, the `provisional_net_ciac_cents` is the base cost plus surcharges minus the allowance footage priced at that same standard unit cost, floored at zero when the allowance would overtake the cost. Fifth, the `provisional_gross_up_cents` is the tax gross-up on the net alone: the net multiplied by twenty-one seventy-ninths, rounded half up to whole cents. Finally, `provisional_total_due_cents` is the net plus the gross-up. The order is contractual: the gross-up base never includes the allowance offset, and the allowance is always valued at the standard unit cost.

The engineer submits the design for utility review (`DRAFT` → `DESIGN_SUBMITTED`), which the parent application's hold must permit. A `NewBusinessRep` then approves the design — possible only while the application itself sits in `DESIGN`, else `ERR_INVALID_STATE`. Approval is a compound event: the main extension moves from `DESIGN_SUBMITTED` to `QUOTED`; a CIAC invoice is created with `amount_due_cents` equal to the provisional total due, in `ISSUED` status (or directly in `PAID` when that total is zero), stamped with the approving rep's identity as `issued_by_user_id`; a timeline commitment is born in `PROPOSED` with its `base_date` set to the approval date (§3.7); and the application advances from `DESIGN` to `QUOTED` with its `quote_valid_until` set to the approval date plus thirty days.

The builder may accept the quote — provided the acting builder owns the application and the current date has not passed `quote_valid_until`; acceptance on or before that date succeeds, and any later attempt is rejected with `ERR_QUOTE_EXPIRED` (HTTP 422). Acceptance moves the main extension from `QUOTED` to `ACCEPTED` and the application from `QUOTED` to `CIAC_PENDING`. When the invoice's amount due is zero, the zero-CIAC chain fires immediately: the invoice stands `PAID` without any payment being recorded, and the application continues straight through from `CIAC_PENDING` to `APPROVED_FOR_CONSTRUCTION` in the same breath.

A quoted design is not frozen. The engineer may send it back to draft — a revision that requires `expected_main_extension_version` to match (§2.7) and requires that no payment has ever been applied to the invoice, else `ERR_INVOICE_HAS_PAYMENTS` (HTTP 409). Revision unwinds the quote: the invoice moves from `ISSUED` to `VOID`, the `PROPOSED` commitment is `CANCELLED`, the application falls back from `QUOTED` to `DESIGN` with its `quote_valid_until` cleared, and the provisional figures are recomputed from whatever updated `design_footage_ft`, `crossings`, or `rock_excavation_expected` the engineer supplied. If the builder simply lets the quote lapse instead, the clock sweep described in §2.9 and §3.9 takes over.

### 3.3. CIAC Invoicing: Payments, Refunds, and Segregation of Duties

The CIAC invoice is the application's fiscal gatekeeper. Beyond the amount due, it tracks `payments_applied_cents` — the running sum of every `PAYMENT` event — `refunds_issued_cents` — the running sum of every `REFUND` event — and `balance_due_cents`, the amount due minus the payments applied. The balance may go momentarily negative only inside a finalization true-up, in which case `refund_required_cents` — zero by default until a refund obligation actually arises — carries the magnitude. Each invoice also denormalizes its `main_extension_id` and `service_application_id` so billing can list invoices by either.

A `BillingClerk` records a payment with an `amount_cents` greater than zero and a `method` of `CHECK`, `ACH`, or `CARD`. Payments are accepted only while the invoice is `ISSUED` or `PARTIALLY_PAID`; any other invoice status is rejected with `ERR_INVOICE_NOT_PAYABLE` (HTTP 409). Two further guards apply, in order of the validation stack: the clerk's identity must differ from the invoice's `issued_by_user_id` — the rep who approved the design may not collect on their own quote, and the attempt is rejected with `ERR_SOD_PAYMENT_BY_ISSUER` (HTTP 422) — and the amount must not exceed the current `balance_due_cents`, else `ERR_OVERPAYMENT` (HTTP 422). A payment smaller than the balance moves `ISSUED` to `PARTIALLY_PAID` (or keeps a `PARTIALLY_PAID` invoice partially paid); a payment exactly equal to the balance moves the invoice to `PAID`, and that event bubbles the application from `CIAC_PENDING` to `APPROVED_FOR_CONSTRUCTION`. Every recorded payment appends a payment event carrying the `ciac_invoice_id`, the `direction` `PAYMENT`, the amount, the method, and the clerk's identity as `recorded_by_user_id`.

Refunds mirror payments under their own segregation rule. While an invoice sits in `REFUND_PENDING` — and only then, else `ERR_INVOICE_NOT_REFUNDABLE` (HTTP 409) — a clerk records a refund against it. The refunding clerk's identity must differ from the `recorded_by_user_id` of every posted payment on that invoice, else `ERR_SOD_REFUND_BY_PAYER` (HTTP 422), and the amount must not exceed the still-outstanding refund — the `refund_required_cents` minus the `refunds_issued_cents` so far — else `ERR_REFUND_AMOUNT_MISMATCH` (HTTP 422). Partial refunds are allowed: the invoice stays `REFUND_PENDING` until the issued refunds exactly equal the required refund, at which point it becomes `REFUNDED`. Each refund appends a `REFUND`-direction payment event in the same append-only ledger.

An invoice in `ISSUED` with zero payments applied can also be voided outright — by a design revision, an application cancellation, or the quote-expiry sweep — moving it to `VOID`.

### 3.4. Permits and Inspections

Permits are the application's interface to municipalities and other authorities. A `PermitCoordinator` creates a permit with its `service_application_id`, a `permit_type` of `ROAD_CUT`, `EASEMENT`, `RAILROAD_CROSSING`, or `DOT_HIGHWAY`, the issuing `jurisdiction`, and a `crossings` list in the same per-segment shape as the design's. Unlike the design's list, a `ROAD_CUT` permit's crossing list must name at least one segment: creating one with an empty or omitted crossing list is rejected with `ERR_INVALID_REQUEST`, while the other permit types accept an empty list. Creation starts the permit in `DRAFT` and computes its `permit_fee_cents`. The fee's rounding order is pinned: for each crossing segment, multiply the segment's length by its width to get square footage, multiply by the surface rate — 350 cents per square foot for `ASPHALT`, 525 for `CONCRETE`, 150 for `LANDSCAPE` — and round that segment fee half up to whole cents before anything is summed; then total the individually rounded segment fees and add the flat filing fee of 7,500 cents ($75.00). Summing raw segment fees and rounding once at the end is a different number and is not the contract.

Filing moves a permit from `DRAFT` to `FILED`, stamps `filed_at`, and — when the application is sitting in `APPROVED_FOR_CONSTRUCTION` — nudges the spine into `PERMITTING`. Filing requires the parent application to be unheld, and a `ROAD_CUT` permit may not be filed with an empty crossing list (`ERR_INVALID_REQUEST`). The authority's answer comes back through the coordinator recording a `decision`: `APPROVED` requires an `expires_at` date on or after the current date — a lapse date in the past is rejected with `ERR_DATE_IN_PAST` (HTTP 422) — while `REJECTED` captures the authority's `decision_note`; either way `decided_at` is stamped. A rejected permit, or an approved one that the clock sweep has since moved from `APPROVED` to `EXPIRED`, can be amended back to `DRAFT` with optional updates to `jurisdiction` or `crossings` — an amendment that supplies an empty crossing list for a `ROAD_CUT` permit meets the same `ERR_INVALID_REQUEST` — and the fee is recomputed whenever the crossings change. Once construction is far enough along — the spine at `SERVICE_INSTALLED` or later, else `ERR_INVALID_STATE` — an approved permit is closed out as `CLOSED`. Permits end in `CLOSED` or `WITHDRAWN`.

Inspections run on a separate half-open window discipline. Inspectors themselves are reference data: a `SystemAdmin` registers each inspector with a `full_name` and a `certifications` list, and inspectors start active. The coordinator schedules an inspection by naming the `service_application_id`, the `inspector_id`, an `inspection_type` of `ROAD_CUT_RESTORATION`, `PRESSURE_TEST`, or `FINAL_SAFETY`, an `inspection_date` that must not lie in the past (`ERR_DATE_IN_PAST`), and a half-open window from `start_minute` to `end_minute` — minutes from local midnight — whose end must fall strictly after its start. The inspector must be active (inactive inspectors reject new inspections with `ERR_INVALID_STATE`, exactly as inactive crews reject new bookings) and certified for the type: the inspector's `certifications` — a subset of `PRESSURE_TEST`, `ROAD_CUT`, and `FINAL_SAFETY` — must contain the member matching the inspection type, else `ERR_INSPECTOR_NOT_CERTIFIED` (HTTP 422). The window must also not overlap any other inspection the same inspector already holds on the same date: a new inspection conflicts when its start falls before an existing inspection's end while its end falls after that inspection's start, and the conflict is rejected with `ERR_INSPECTOR_WINDOW_CONFLICT` (HTTP 409). Because the intervals are half-open, back-to-back adjacency — one window's end exactly equal to the next window's start — is allowed. A new inspection is born directly in `SCHEDULED`.

Results are personal. Only the inspector named on the inspection may record its outcome — anyone else's attempt meets `ERR_FORBIDDEN_OWNER` — supplying a `result` of `PASS` or `FAIL` and an optional `notes` free-text that is persisted as `result_notes`. A pass moves the inspection to the terminal `COMPLETED_PASS`; a fail moves it to `COMPLETED_FAIL`, which is deliberately non-terminal so the fail-reschedule-reinspect loop can cycle. The coordinator may reschedule a failed inspection — or one the clock swept from `SCHEDULED` to `EXPIRED` — back to `SCHEDULED` with a fresh `inspection_date`, `start_minute`, and `end_minute`, re-running the same creation-time checks: date not in the past, certification coverage, and window conflict. A still-`SCHEDULED` inspection may also be cancelled outright as `CANCELLED`.

### 3.5. Crew Bookings and Construction Scheduling

Field capacity is administered centrally. A `SystemAdmin` registers each crew with a `crew_name`, a `specialty` of `MAIN_EXTENSION`, `SERVICE_LINE`, `RESTORATION`, or `GENERAL`, and a `daily_capacity_minutes` greater than zero; crews start `active`. A `FieldSupervisor` requests a construction window by naming the `service_application_id`, the `field_crew_id`, a `work_date`, a window from `start_minute` to `end_minute` expressed as minutes from local midnight (the start between 0 and 1439, the end no later than 1440 and strictly after the start), and a `scope` of `MAIN_CONSTRUCTION`, `SERVICE_INSTALL`, or `RESTORATION`. The booking starts in `REQUESTED`.

Confirmation is where the discipline lives. Confirming requires the `work_date` to be today or later (`ERR_DATE_IN_PAST`), the crew to be active (`ERR_INVALID_STATE`), and the window to fit the crew's day twice over. First, the buffered-overlap rule: crew windows behave as closed intervals padded by a thirty-minute turnaround buffer, so the new booking conflicts with any already-`CONFIRMED` booking of the same crew on the same date whenever the new start falls before the existing window's end plus thirty minutes and the new end plus thirty minutes falls after the existing window's start — adjacency closer than thirty minutes is a conflict (`ERR_CREW_WINDOW_CONFLICT`, HTTP 409), while a gap of exactly thirty minutes or more is allowed. Second, the capacity rule: the sum of the durations of that crew's `CONFIRMED` bookings on that date, plus the new booking's duration, must not exceed the crew's `daily_capacity_minutes`; a total exactly equal to capacity is allowed, anything larger is rejected with `ERR_CREW_CAPACITY_EXCEEDED` (HTTP 422). A confirmed booking can be rescheduled — a new `work_date`, `start_minute`, and `end_minute` are stored and the booking drops back to `REQUESTED`, requiring fresh confirmation — or cancelled, and cancelling a confirmed booking releases its minutes back into the crew-day capacity. When a confirmed booking is marked complete, two things happen at once: the application moves from `CONSTRUCTION_SCHEDULED` to `SERVICE_INSTALLED`, and its main extension moves from `ACCEPTED` to `CONSTRUCTED`.

The scheduling gate itself belongs to the supervisor. Moving an application from `APPROVED_FOR_CONSTRUCTION` or `PERMITTING` to `CONSTRUCTION_SCHEDULED` enforces five checks: the application must be unheld (`ERR_APPLICATION_ON_HOLD`); every permit of the application must be in `APPROVED` or `CLOSED` (`ERR_PERMIT_NOT_APPROVED`, HTTP 422); when the design's `crossings_count` is greater than zero, at least one `ROAD_CUT` permit specifically must be in `APPROVED` or `CLOSED` (same error); at least one of the application's bookings must be `CONFIRMED` (`ERR_NO_CONFIRMED_BOOKING`, HTTP 422); and the CIAC invoice must be `PAID` (`ERR_CIAC_UNPAID`, HTTP 422).

### 3.6. Meter Sets, Purge & Leak Tests, and Appliance Turn-On

With the service line in, the meter work begins. A `MeterTechnician` creates the application's meter set from its `service_application_id`; it starts in `PLANNED`, and an application may have at most one non-`CANCELLED` meter set (`ERR_DUPLICATE_METER_SET`, HTTP 409). Sizing belongs to the `DesignEngineer` and is only meaningful once loads are locked — the spine must be at `LOAD_CONFIRMED` or later, else `ERR_INVALID_STATE`. Sizing compares the application's `diversity_adjusted_load_cfph` against five meter models whose base capacities are 425, 800, 1,400, 2,300, and 5,000 cubic feet per hour — the models `AL_425`, `AL_800`, `AL_1400`, `AL_2300`, and `AL_5000` respectively. When the application's `pressure_class_requested` is `MEDIUM`, each model's capacity doubles; `LOW` leaves capacities at face value. The selected `meter_model` is the model with the smallest pressure-adjusted capacity that still covers the diversity-adjusted load, and a capacity exactly equal to the load selects that model rather than the next size up. Each meter pairs with exactly one regulator, recorded as `regulator_model`: `AL_425` with `R_325`, `AL_800` with `R_750`, `AL_1400` with `R_1200`, `AL_2300` with `R_2100`, and `AL_5000` with `R_4500`. When even the largest model's adjusted capacity falls short, sizing is rejected with `ERR_METER_SIZE_UNAVAILABLE` (HTTP 422). A sized set moves from `PLANNED` to `SIZED`.

The technician then records the order — supplying the device `serial_number`, moving the set from `SIZED` to `ORDERED` — and installs it. Installation requires the application to be exactly at `SERVICE_INSTALLED`, else `ERR_SERVICE_LINE_NOT_INSTALLED` (HTTP 409); a successful install stamps `installed_by_user_id` and `installed_at`, moves the set from `ORDERED` to `INSTALLED`, and pushes the application from `SERVICE_INSTALLED` into `METER_WORK`.

Every meter set must prove itself with a documented purge and leak test. The installing technician records one against a `meter_set_id` with four measured values: `purge_duration_min`, `test_pressure_psi`, `test_duration_min`, and `observed_pressure_drop_psi`. Safety minima are hard: at least five minutes of purge, at least 10.0 psi of test pressure, and at least fifteen minutes of pressure hold — any shortfall is rejected with `ERR_TEST_PARAMS_UNSAFE` (HTTP 422). Only one test per meter set may sit in `RECORDED` at a time (`ERR_TEST_ALREADY_ACTIVE`, HTTP 409). At record time the system computes the acceptance criterion: the `max_allowed_drop_psi` is the reference allowance of 0.300 psi over a reference duration of sixty minutes, scaled by the actual hold — 0.300 multiplied by 60, divided by the test's duration in minutes — rounded half up to three decimal places. The computed `result` is `PASS` when the observed drop is less than or equal to that allowance — a drop exactly equal to the allowed maximum passes — and `FAIL` when it is greater. Recording the test moves the meter set from `INSTALLED` (or from `REPAIR`, after a repair loop) to `TESTING` and the application from `METER_WORK` to `TESTING`, and stamps the technician's identity as `installer_user_id`.

Certification belongs to a different pair of hands. An `Inspector` acting as witness must hold the `PRESSURE_TEST` certification (`ERR_INSPECTOR_NOT_CERTIFIED`) and must not be the technician who recorded the test — a witness identity equal to the test's `installer_user_id` is rejected with `ERR_SOD_WITNESS_IS_INSTALLER` (HTTP 422). Certifying stamps `witness_inspector_id` and moves the test from `RECORDED` to `CERTIFIED`, with a two-link consequence: when the result is `PASS`, the meter set moves from `TESTING` to `READY_FOR_TURN_ON` and the application bubbles from `TESTING` to `TURN_ON`; when the result is `FAIL`, the meter set drops to `REPAIR`, from which the technician's mark-repaired returns it to `INSTALLED` for another attempt. A witness may instead reject the documentation outright with a `rejection_reason`, moving the test from `RECORDED` to `REJECTED`; the meter set then remains in `TESTING` and a fresh test may be recorded.

Turn-on is per appliance. The technician schedules a turn-on event by naming the `service_application_id` and the `appliance_load_id` — which must belong to that same application, else `ERR_LOAD_APP_MISMATCH` (HTTP 422); the event starts in `SCHEDULED` with the technician recorded as `technician_user_id`. Completing the event is possible only while the application sits in `TURN_ON` (else `ERR_METER_NOT_READY`, HTTP 409) and captures four safety observations: `co_reading_ppm` at one decimal, `odor_detected`, `ignition_verified`, and `venting_verified`. The event becomes `VERIFIED` if and only if no odor was detected, ignition verified, venting verified, and the carbon-monoxide reading is strictly below 9.0 parts per million — a reading of exactly 9.0 fails; any other outcome makes it `FAILED`. A failed event can be re-opened from `FAILED` back to `SCHEDULED` for another attempt.

Energization is the meter shop's final act. The technician may turn the gas on only when the application is unheld, the meter set stands at `READY_FOR_TURN_ON` (else `ERR_METER_NOT_READY`), and every appliance load of the application has at least one `VERIFIED` turn-on event (else `ERR_TURN_ON_INCOMPLETE`, HTTP 422). Energizing moves the application from `TURN_ON` to `ENERGIZED` and the meter set from `READY_FOR_TURN_ON` to `ENERGIZED` with it.

### 3.7. Timeline Commitments and Delay Credits

The commitment born at design approval is the utility's promise to the builder. It stores the approval date as `base_date` and two computed dates side by side. The `optimistic_completion_date` assumes the fastest plausible path: when the design crosses anything (its `crossings_count` is greater than zero), ten calendar days of statutory-minimum permitting; then construction at one hundred fifty feet per day with the design footage divided by that rate and rounded up to whole days; then five days for the meter set. The `conservative_completion_date` assumes the median path: twenty calendar days of jurisdiction-median permitting when crossings exist, construction at one hundred feet per day rounded up the same way, the same five meter-set days, and a further five-day buffer. Both are calendar-day offsets from the base date, and the conservative date is always at least the optimistic one — strictly later whenever footage or permit terms differ. The `committed_completion_date` starts life equal to the conservative date.

The builder accepts the proposed commitment (`PROPOSED` → `ACCEPTED`; ownership applies). Later, the builder may propose a different committed date — but only from `ACCEPTED` (any other status is rejected with `ERR_COMMITMENT_NOT_REVISABLE`, HTTP 409), with `expected_commitment_version` matching per §2.7, and with a `requested_completion_date` that falls strictly after the current date; one on the current date or in the past is rejected with `ERR_DATE_IN_PAST`. The proposal parks the commitment in `REVISION_PENDING` until a `NewBusinessRep` responds: a `decision` of `ACCEPT` replaces the `committed_completion_date` with the requested date and clears `requested_completion_date`, while `REJECT` leaves the committed date untouched and clears the request — both paths land back in `ACCEPTED`.

When slippage emerges, the rep flags the commitment with a `delay_attribution` of `UTILITY`, `BUILDER`, `MUNICIPALITY`, or `WEATHER` together with an `expected_completion_date`; the first flag moves `ACCEPTED` to `AT_RISK`, and further flags update an already-`AT_RISK` commitment in place. If the current date passes the committed date while the application remains incomplete, the clock sweep moves the commitment from `ACCEPTED` or `AT_RISK` to `MISSED`, defaulting the attribution to `UTILITY` when none was ever recorded. Application completion resolves the commitment instead: finishing on or before the committed date makes it `MET`; finishing later makes it `MISSED` with the same attribution default.

A `MISSED` commitment attributed to the utility costs money. The `penalty_credit_cents` — zero by default — is computed at application completion from the calendar days between the committed and actual completion dates: zero or negative days late means the commitment was met and no credit accrues; otherwise each of the first five late days earns 2,500 cents ($25.00) and each late day beyond the fifth earns 5,000 cents, with the total capped at 50,000 cents ($500.00). The credit applies only when the delay attribution is `UTILITY`; attribution to the builder, the municipality, or the weather yields zero.

### 3.8. As-Built True-Up, GIS Closeout, and Application Completion

Construction rarely matches the design exactly. Once the spine has reached `SERVICE_INSTALLED` or later (else `ERR_INVALID_STATE`), a `FieldSupervisor` records the as-built reality — `actual_footage_ft`, the blended `actual_unit_cost_cents` per foot, the `actual_rock_excavation` flag, and the `actual_crossings` list — moving the main extension from `CONSTRUCTED` to `AS_BUILT_RECORDED`. A `BillingClerk` then finalizes it, running the same CIAC shape over the as-built inputs: the final base is the actual footage at the actual unit cost; the final surcharges are 15,000 cents per as-built crossing segment plus 2,000 cents per actual foot when rock was actually encountered; the final net, `final_net_ciac_cents`, is that sum minus the same appliance-driven allowance priced at the standard 4,500 cents per foot, floored at zero; the `final_gross_up_cents` is again twenty-one seventy-ninths of the final net, rounded half up to whole cents; and the `final_total_due_cents` is their sum. The signed `ciac_delta_cents` is the final total minus the provisional total. The invoice is then trued-up: an invoice already `PAID` has its `amount_due_cents` repriced to the final total on every arm of the true-up — reopening to `ISSUED` when the delta is positive; moving to `REFUND_PENDING`, with `refund_required_cents` set to the payments applied minus the final total — the negated delta — when the delta is negative; and settling to `SETTLED` when the delta is exactly zero — and in all three cases its `balance_due_cents` is then recomputed as the repriced amount due minus the payments applied, so on the downward arm the balance goes negative by exactly the refund magnitude §3.3 describes. An invoice still `ISSUED` and unpaid simply keeps that status with its amount repriced to the final total. Finalization moves the main extension to its terminal `FINALIZED` state.

The last artefact is geographic. A `FieldSupervisor` submits the as-built GIS record — the `service_application_id`, the `geometry_geojson` LineString of the installed service and main extension, a `pipe_material` of `STEEL`, `PE`, or `CSST`, and the cover `depth_inches` — which is accepted only while the application is `ENERGIZED` or already in `GIS_REVIEW`, and only once per application (`ERR_DUPLICATE_GIS`, HTTP 409). Submission starts the record in `SUBMITTED`, stamps `submitted_by_user_id`, and slides the application from `ENERGIZED` into `GIS_REVIEW`. A `GISAnalyst` then validates it — cover depth of at least eighteen inches is code, and anything shallower is rejected with `ERR_GIS_DEPTH_VIOLATION` (HTTP 422) — stamping `validated_by_user_id` as the record moves to the terminal `VALIDATED`; or the analyst rejects it with a `rejection_reason`, sending it to `REJECTED`, from which the supervisor may resubmit corrected `geometry_geojson`, `pipe_material`, or `depth_inches` and return it to `SUBMITTED`.

Completion is the rep's final checklist, reachable from `ENERGIZED` or `GIS_REVIEW`. It demands an unheld application, a `VALIDATED` GIS as-built on file (`ERR_GIS_NOT_VALIDATED`, HTTP 422), a `FINALIZED` main extension (`ERR_INVALID_STATE`), and a CIAC invoice in `SETTLED` or `REFUNDED` (`ERR_CIAC_UNPAID`). Completing stamps `completed_at`, resolves the timeline commitment to `MET` or `MISSED` with the penalty credit computed as §3.7 describes, and moves the application to `COMPLETED`.

### 3.9. Holds, Cancellation, and Expiry Unwinding

Either side can freeze an application. Holding it with a free-text `reason` — recorded on the application as `hold_reason` — sets the hold axis to `HELD_BY_BUILDER` when the actor is the owning `Builder`, or to `HELD_BY_UTILITY` when the actor is a `NewBusinessRep` or `FieldSupervisor`; resuming clears it back to `NOT_HELD`. Neither action touches the spine, but while any hold is in force the freeze of §2.5 applies to every child mutation and every spine transition.

Cancellation is the heaviest operation in the system. The owning builder or a `NewBusinessRep` may cancel any application that is not already in a terminal state (`COMPLETED`, `REJECTED`, `CANCELLED`, or `EXPIRED` — attempts there meet `ERR_APPLICATION_TERMINAL`); a builder acting on someone else's application meets `ERR_FORBIDDEN_OWNER`, and any other role meets `ERR_UNAUTHORIZED_ROLE`. The cancel cascade then unwinds every child in one atomic move, link by link. A non-terminal main extension moves to `CANCELLED` — and that cancellation forces its invoice: an `ISSUED` invoice with no payments becomes `VOID`, while a `PARTIALLY_PAID` or `PAID` invoice becomes `REFUND_PENDING` with `refund_required_cents` set to everything collected so far, to be unwound through the refund flow of §3.3. Permits in `DRAFT` or `FILED` are `WITHDRAWN`; permits in `APPROVED` or `CLOSED` are never withdrawn — they remain on file as the municipal record. Bookings in `REQUESTED` or `CONFIRMED` are `CANCELLED`, releasing any held crew-day minutes; inspections still `SCHEDULED` are `CANCELLED`; turn-on events in `SCHEDULED` or `FAILED` are `CANCELLED`. A non-terminal meter set is `CANCELLED`, and any of its purge and leak tests still in `RECORDED` are `REJECTED`. A non-terminal timeline commitment — whether `PROPOSED`, `ACCEPTED`, `REVISION_PENDING`, or `AT_RISK` — is `CANCELLED`, and a GIS record in `SUBMITTED` or `REJECTED` is `CANCELLED` alongside it.

Expiry unwinds more gently but along the same rails. When the clock sweep of §2.9 finds an application still `QUOTED` more than seven days past its `quote_valid_until`, it moves the application to `EXPIRED` and cascades: the main extension follows from `QUOTED` to `EXPIRED`; the invoice is voided when nothing has been paid, or — with money already applied — moves from `ISSUED` or `PARTIALLY_PAID` to `REFUND_PENDING` with the full collected amount as `refund_required_cents`; and any non-terminal commitment is `CANCELLED`. Throughout the seven-day grace window itself the application simply stays `QUOTED`, with quote acceptance already refusing with `ERR_QUOTE_EXPIRED`, giving the builder one last week to renegotiate before the sweep acts.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource or drive an action on it return `200 OK`; the single destructive operation (removing an appliance load) returns `204 No Content` with an empty body. All collections are mounted directly under the API root. The table below is a summary only — request bodies, response payloads, computed fields, and side effects are specified in §2 and §3, not here.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/builders` | Register a builder account | NewBusinessRep, SystemAdmin |
| GET | `/builders/{id}` | Get one builder | Any authenticated role |
| GET | `/builders` | List builders, optionally filtered by status | Any authenticated role |
| PATCH | `/builders/{id}` | Suspend or reactivate a builder | SystemAdmin |
| POST | `/service-applications` | Create a draft new-service application | Builder |
| GET | `/service-applications/{id}` | Get one application | Any authenticated role |
| GET | `/service-applications` | List applications, optionally filtered by builder or status | Any authenticated role |
| PATCH | `/service-applications/{id}` | Edit draft application header fields (OCC) | Builder |
| POST | `/service-applications/{id}/submit` | Submit the application and run the load calculation | Builder |
| POST | `/service-applications/{id}/confirm-load` | Confirm the load calculation and lock the loads | NewBusinessRep |
| POST | `/service-applications/{id}/reject` | Reject a submitted application | NewBusinessRep |
| POST | `/service-applications/{id}/schedule-construction` | Gate-checked transition to construction scheduled | FieldSupervisor |
| POST | `/service-applications/{id}/energize` | Turn gas on after all turn-ons are verified | MeterTechnician |
| POST | `/service-applications/{id}/complete` | Close out the application and resolve the commitment | NewBusinessRep |
| POST | `/service-applications/{id}/hold` | Place a hold on the application | Builder, NewBusinessRep, FieldSupervisor |
| POST | `/service-applications/{id}/resume` | Clear the application's hold | Builder, NewBusinessRep, FieldSupervisor |
| POST | `/service-applications/{id}/cancel` | Cancel the application with the full compensation cascade | Builder, NewBusinessRep |
| GET | `/service-applications/{id}/readiness` | Computed posture read with blockers and live counters | Any authenticated role |
| POST | `/appliance-loads` | Add an appliance load to an application | Builder |
| GET | `/appliance-loads/{id}` | Get one appliance load | Any authenticated role |
| GET | `/appliance-loads` | List appliance loads, optionally filtered by application | Any authenticated role |
| PATCH | `/appliance-loads/{id}` | Edit a load while the application is a draft (OCC) | Builder |
| DELETE | `/appliance-loads/{id}` | Remove a load while the application is a draft | Builder |
| POST | `/main-extensions` | Create a main-extension design with provisional CIAC | DesignEngineer |
| GET | `/main-extensions/{id}` | Get one main extension | Any authenticated role |
| GET | `/main-extensions` | List main extensions, optionally filtered by application | Any authenticated role |
| POST | `/main-extensions/{id}/submit-design` | Submit the design for utility review | DesignEngineer |
| POST | `/main-extensions/{id}/approve-design` | Approve the design, issuing the CIAC invoice and timeline commitment | NewBusinessRep |
| POST | `/main-extensions/{id}/accept-quote` | Builder accepts the quote before expiry | Builder |
| POST | `/main-extensions/{id}/revise` | Send a quoted design back to draft (OCC) | DesignEngineer |
| POST | `/main-extensions/{id}/record-as-built` | Record as-built footage and costs | FieldSupervisor |
| POST | `/main-extensions/{id}/finalize` | Run the final CIAC true-up and reconcile the invoice | BillingClerk |
| GET | `/ciac-invoices/{id}` | Get one invoice | Any authenticated role |
| GET | `/ciac-invoices` | List invoices, optionally filtered by main extension or application | Any authenticated role |
| POST | `/ciac-invoices/{id}/payments` | Record a CIAC payment | BillingClerk |
| POST | `/ciac-invoices/{id}/refunds` | Record a CIAC refund | BillingClerk |
| GET | `/ciac-payments/{id}` | Get one payment or refund event | Any authenticated role |
| GET | `/ciac-payments` | List payment and refund events, optionally filtered by invoice | Any authenticated role |
| POST | `/permits` | Create a permit with a computed fee | PermitCoordinator |
| GET | `/permits/{id}` | Get one permit | Any authenticated role |
| GET | `/permits` | List permits, optionally filtered by application, type, or status | Any authenticated role |
| POST | `/permits/{id}/file` | File the permit with the authority | PermitCoordinator |
| POST | `/permits/{id}/record-decision` | Record the authority's decision | PermitCoordinator |
| POST | `/permits/{id}/amend` | Amend a rejected or expired permit back to draft | PermitCoordinator |
| POST | `/permits/{id}/close` | Close an approved permit after construction | PermitCoordinator |
| POST | `/field-crews` | Register a field crew | SystemAdmin |
| GET | `/field-crews/{id}` | Get one field crew | Any authenticated role |
| GET | `/field-crews` | List field crews | Any authenticated role |
| POST | `/crew-bookings` | Request a construction window on a crew | FieldSupervisor |
| GET | `/crew-bookings/{id}` | Get one booking | Any authenticated role |
| GET | `/crew-bookings` | List bookings, optionally filtered by crew, application, date, or status | Any authenticated role |
| POST | `/crew-bookings/{id}/confirm` | Confirm a booking under the overlap and capacity rules | FieldSupervisor |
| POST | `/crew-bookings/{id}/complete` | Mark construction complete | FieldSupervisor |
| POST | `/crew-bookings/{id}/cancel` | Cancel a booking, releasing crew-day minutes | FieldSupervisor |
| POST | `/crew-bookings/{id}/reschedule` | Move a confirmed booking to a new window | FieldSupervisor |
| POST | `/inspectors` | Register an inspector | SystemAdmin |
| GET | `/inspectors/{id}` | Get one inspector | Any authenticated role |
| GET | `/inspectors` | List inspectors | Any authenticated role |
| POST | `/inspections` | Schedule an inspection | PermitCoordinator |
| GET | `/inspections/{id}` | Get one inspection | Any authenticated role |
| GET | `/inspections` | List inspections, optionally filtered by inspector, application, or status | Any authenticated role |
| POST | `/inspections/{id}/record-result` | The assigned inspector records pass or fail | Inspector |
| POST | `/inspections/{id}/cancel` | Cancel a scheduled inspection | PermitCoordinator |
| POST | `/inspections/{id}/reschedule` | Re-schedule a failed or expired inspection | PermitCoordinator |
| POST | `/meter-sets` | Create the meter set for an application | MeterTechnician |
| GET | `/meter-sets/{id}` | Get one meter set | Any authenticated role |
| GET | `/meter-sets` | List meter sets, optionally filtered by application | Any authenticated role |
| POST | `/meter-sets/{id}/size` | Run meter sizing, selecting the meter and regulator | DesignEngineer |
| POST | `/meter-sets/{id}/mark-ordered` | Record the meter order with its device serial | MeterTechnician |
| POST | `/meter-sets/{id}/install` | Install the meter set | MeterTechnician |
| POST | `/meter-sets/{id}/mark-repaired` | Close a repair loop back to installed | MeterTechnician |
| POST | `/purge-leak-tests` | Document a purge and leak test | MeterTechnician |
| GET | `/purge-leak-tests/{id}` | Get one test record | Any authenticated role |
| GET | `/purge-leak-tests` | List test records, optionally filtered by meter set | Any authenticated role |
| POST | `/purge-leak-tests/{id}/certify` | Witness-certify a recorded test | Inspector |
| POST | `/purge-leak-tests/{id}/reject` | Witness rejects the test documentation | Inspector |
| POST | `/turn-on-events` | Schedule an appliance turn-on and safety check | MeterTechnician |
| GET | `/turn-on-events/{id}` | Get one turn-on event | Any authenticated role |
| GET | `/turn-on-events` | List turn-on events, optionally filtered by application, load, or status | Any authenticated role |
| POST | `/turn-on-events/{id}/complete` | Record the safety-check results | MeterTechnician |
| POST | `/turn-on-events/{id}/retry` | Re-open a failed turn-on for another attempt | MeterTechnician |
| GET | `/timeline-commitments/{id}` | Get one commitment | Any authenticated role |
| GET | `/timeline-commitments` | List commitments, optionally filtered by application | Any authenticated role |
| POST | `/timeline-commitments/{id}/accept` | Builder accepts the proposed commitment | Builder |
| POST | `/timeline-commitments/{id}/propose-revision` | Builder proposes a new committed date (OCC) | Builder |
| POST | `/timeline-commitments/{id}/respond-revision` | Utility accepts or rejects the proposed revision | NewBusinessRep |
| POST | `/timeline-commitments/{id}/mark-delayed` | Flag a commitment at risk with delay attribution | NewBusinessRep |
| POST | `/gis-as-builts` | Submit the as-built GIS record | FieldSupervisor |
| GET | `/gis-as-builts/{id}` | Get one GIS record | Any authenticated role |
| GET | `/gis-as-builts` | List GIS records, optionally filtered by application | Any authenticated role |
| POST | `/gis-as-builts/{id}/validate` | Validate the as-built with the depth code check | GISAnalyst |
| POST | `/gis-as-builts/{id}/reject` | Reject the as-built | GISAnalyst |
| POST | `/gis-as-builts/{id}/resubmit` | Resubmit a rejected as-built with corrections | FieldSupervisor |
| POST | `/_clock/set_current_utc` | Set the logical clock and run all time-based sweeps atomically | SystemAdmin |

## 5. Error Code Catalogue

Trigger conditions for each error live in the narrative of §2 and §3; this table is the lookup of identifier to HTTP status.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_UNAUTHORIZED_ROLE` | 403 Forbidden |
| `ERR_FORBIDDEN_OWNER` | 403 Forbidden |
| `ERR_BUILDER_NOT_FOUND` | 404 Not Found |
| `ERR_APPLICATION_NOT_FOUND` | 404 Not Found |
| `ERR_LOAD_NOT_FOUND` | 404 Not Found |
| `ERR_MAIN_EXTENSION_NOT_FOUND` | 404 Not Found |
| `ERR_INVOICE_NOT_FOUND` | 404 Not Found |
| `ERR_PAYMENT_NOT_FOUND` | 404 Not Found |
| `ERR_PERMIT_NOT_FOUND` | 404 Not Found |
| `ERR_CREW_NOT_FOUND` | 404 Not Found |
| `ERR_BOOKING_NOT_FOUND` | 404 Not Found |
| `ERR_INSPECTOR_NOT_FOUND` | 404 Not Found |
| `ERR_INSPECTION_NOT_FOUND` | 404 Not Found |
| `ERR_METER_SET_NOT_FOUND` | 404 Not Found |
| `ERR_TEST_NOT_FOUND` | 404 Not Found |
| `ERR_TURN_ON_NOT_FOUND` | 404 Not Found |
| `ERR_COMMITMENT_NOT_FOUND` | 404 Not Found |
| `ERR_GIS_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_APPLICATION_TERMINAL` | 409 Conflict |
| `ERR_APPLICATION_ON_HOLD` | 409 Conflict |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_INVOICE_NOT_PAYABLE` | 409 Conflict |
| `ERR_INVOICE_NOT_REFUNDABLE` | 409 Conflict |
| `ERR_COMMITMENT_NOT_REVISABLE` | 409 Conflict |
| `ERR_SERVICE_LINE_NOT_INSTALLED` | 409 Conflict |
| `ERR_METER_NOT_READY` | 409 Conflict |
| `ERR_QUOTE_EXPIRED` | 422 Unprocessable Entity |
| `ERR_DATE_IN_PAST` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_MAIN_EXTENSION` | 409 Conflict |
| `ERR_DUPLICATE_METER_SET` | 409 Conflict |
| `ERR_DUPLICATE_GIS` | 409 Conflict |
| `ERR_LOADS_LOCKED` | 409 Conflict |
| `ERR_TEST_ALREADY_ACTIVE` | 409 Conflict |
| `ERR_INSPECTOR_NOT_CERTIFIED` | 422 Unprocessable Entity |
| `ERR_CREW_WINDOW_CONFLICT` | 409 Conflict |
| `ERR_INSPECTOR_WINDOW_CONFLICT` | 409 Conflict |
| `ERR_CREW_CAPACITY_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_METER_SIZE_UNAVAILABLE` | 422 Unprocessable Entity |
| `ERR_BUILDER_SUSPENDED` | 422 Unprocessable Entity |
| `ERR_NO_APPLIANCE_LOADS` | 422 Unprocessable Entity |
| `ERR_INVOICE_HAS_PAYMENTS` | 409 Conflict |
| `ERR_TEST_PARAMS_UNSAFE` | 422 Unprocessable Entity |
| `ERR_SOD_WITNESS_IS_INSTALLER` | 422 Unprocessable Entity |
| `ERR_SOD_PAYMENT_BY_ISSUER` | 422 Unprocessable Entity |
| `ERR_SOD_REFUND_BY_PAYER` | 422 Unprocessable Entity |
| `ERR_GIS_DEPTH_VIOLATION` | 422 Unprocessable Entity |
| `ERR_PERMIT_NOT_APPROVED` | 422 Unprocessable Entity |
| `ERR_NO_CONFIRMED_BOOKING` | 422 Unprocessable Entity |
| `ERR_TURN_ON_INCOMPLETE` | 422 Unprocessable Entity |
| `ERR_GIS_NOT_VALIDATED` | 422 Unprocessable Entity |
| `ERR_LOAD_APP_MISMATCH` | 422 Unprocessable Entity |
| `ERR_CIAC_UNPAID` | 422 Unprocessable Entity |
| `ERR_OVERPAYMENT` | 422 Unprocessable Entity |
| `ERR_REFUND_AMOUNT_MISMATCH` | 422 Unprocessable Entity |
