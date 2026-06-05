# Solar Install Financing API — Product Requirements Document

## 1. Introduction

Rooftop solar adoption stalls less on hardware and more on the tangle of paperwork, money, and grid coordination that surrounds it: a homeowner must commission a sunlight assessment, contract a licensed installer, choose between three radically different financing structures, satisfy a utility's interconnection review, and then live for twenty-five years with the consequences of those early decisions. The Solar Install Financing API exists to model that entire lifecycle as a coherent set of resources and state transitions, so that every party — the property owner, the installer, the utility, the certificate broker, and the platform operator — works against the same authoritative record.

This platform orchestrates a project from its first request through design, permitting, installation, inspection, grid permission-to-operate, and into long-term operation. Along the way it tracks the money: which of the three financing models (a power-purchase agreement, a lease, or a loan) governs the economics, who books the Federal Investment Tax Credit, who owns the Solar Renewable Energy Certificates the system mints, and how each monthly net-metering period reconciles production against consumption. Because financing choice forks both the downstream cash flows and the ownership of incentives, the system must capture that branch precisely and propagate its effects deterministically.

Two cross-cutting disciplines run through everything below. First, the platform is a ledger: feeder capacity, kWh banks, certificate pools, and credit attributions are conserved quantities that must balance after every operation. Second, several operations touch more than one resource at once, so the document is explicit about cascades, compensating actions, and the optimistic-concurrency guards that keep concurrent writers from corrupting a shared snapshot.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request other than the anonymous registration endpoints must carry two headers: `X-User-ID`, identifying the calling principal, and `X-User-Role`, naming the role under which the call is made. A request missing either header is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is not permitted to perform the requested operation is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403). When a role is permitted in general but the acting principal does not own the specific resource being acted upon, the request is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403).

The system recognizes six roles, spelled exactly as follows: `Anonymous`, `Homeowner`, `SolarInstaller`, `Utility`, `SrecBroker`, and `PlatformAdmin`.

`Anonymous` is an unauthenticated caller and may only register new accounts; it is the only role permitted to create homeowners, installers, and brokers, and it owns no persisted identity. The four entity-backed roles tie `X-User-ID` to a stored record: when `X-User-Role` is `Homeowner`, `X-User-ID` is the `id` of the acting `Homeowner`, and ownership checks on any resource that references a homeowner compare that resource's `homeowner_id` to `X-User-ID`; when `X-User-Role` is `SolarInstaller`, `X-User-ID` is the `id` of the acting `SolarInstaller`, and ownership checks compare a project's `installer_id` to `X-User-ID`; when `X-User-Role` is `Utility`, `X-User-ID` is the `id` of the acting `Utility`, and ownership checks compare an interconnection application's `utility_id` to `X-User-ID`; when `X-User-Role` is `SrecBroker`, `X-User-ID` is the `id` of the acting `SrecBroker`. By contrast, `PlatformAdmin` is an opaque operator identifier not tied to any persisted entity; the server accepts the header for authentication and authorization but does not compare it to any entity's `id`.

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

List endpoints accept two query parameters, `limit` and `offset`. The `limit` defaults to 10 when omitted, with a minimum of 1 and a maximum of 100; an explicit value outside this band is clamped or rejected as an invalid request. The `offset` defaults to 0 and may not be negative. Results are always ordered by `created_at` ascending. The `meta` block of a list response carries the four pagination fields `limit`, `offset`, `total_count`, and `has_more`, where `total_count` reflects the full count of matching resources before the page window is applied and `has_more` indicates whether further pages remain.

### 2.4. Resource Identity, Versioning, and Timestamps

Every resource carries a server-minted `id` that is a UUID with no type prefix; it is identity only and is never accepted as a business-decision input. Most resources also carry `created_at` and `updated_at` timestamps, both ISO 8601 UTC with three fractional digits, and an integer `version`. The `version` begins at 1 on creation and increments by exactly 1 on every mutation, including mutations that arrive as a cascade from an operation on another resource. The `updated_at` timestamp is refreshed on every such mutation as well, while `created_at` is fixed at creation.

One entity is deliberately lighter: a `WarrantyPolicy` is an immutable artifact minted when a project becomes operational, and so it carries only `id` and `created_at`. It has no `updated_at` and no `version`, because once written it is never mutated. Every other entity in the system carries the full quartet of common fields.

### 2.5. Nested Retrieval and Reverse-Reachability Lookups

The entity model is flat: projects, financing plans, certificates, sales, periods, applications, policies, and claims are peers linked by foreign keys rather than nested under one another in the URL hierarchy. Single-resource reads validate their path identifier and return `ERR_NOT_FOUND` (HTTP 404) when the resource does not exist. List endpoints support reverse-reachability filters so a caller can walk from a parent to its children: projects may be filtered by `homeowner_id`, `installer_id`, or `financing_plan_id`; financing plans by `project_id`; interconnection applications by `project_id` or `utility_id`; certificates by `project_id`, `srec_sale_id`, or `status`; sales by `project_id` or `broker_id`; net-meter periods by `project_id` or `status`; warranty policies by `project_id`; and warranty claims by `project_id` or `status`.

### 2.6. Monetary Precision and Rounding

All money is stored and computed in integer cents. Wherever a calculation produces a fractional cent it is resolved by rounding half up to the nearest whole cent. Production figures are whole kilowatt-hours, also rounded half up unless a specific rule states a floor. System sizing is the exception to half-up rounding: the kilowatt figure is carried to two decimal places and truncated toward zero (floored), never rounded up. Each calculation section below restates its own precision so the rule travels with the formula.

### 2.7. Cascades, Compensating Actions, and Cross-Entity Effects

Several transitions mutate more than the resource named in the request. Cancelling a project, when that project already has an attached financing plan, terminates that plan as a depth-one cascade. Granting permission-to-operate on an interconnection application drives the underlying project to its operational terminal state and mints the project's warranty policy — a cross-entity effect originating two resources away from the project itself. Approving an interconnection decrements the reviewing utility's feeder capacity, and withdrawing an already-approved interconnection restores exactly that same amount, conserving total feeder capacity across the approve/withdraw pair. In every case, each mutated resource has its own `version` incremented and its own `updated_at` refreshed; a cascade is not exempt from versioning.

### 2.8. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency against the parent `Project`. In both, the request body must carry `expected_project_version` as a required field holding the project `version` the client last observed, and in both a mismatch with the project's current `version` is rejected with `ERR_STALE_PROJECT_VERSION` (HTTP 412).

The first guarded operation is creating a certificate sale. A sale sweeps every listed certificate of a given project and vintage into a single transaction; if the client's `expected_project_version` no longer matches — for instance because another sale already swept and emptied the listed pool, or because newly minted certificates or settled periods advanced the project version since the client read it — the create is rejected so the sweep always reflects a snapshot the client actually observed rather than whatever the listed pool happens to hold at execution time.

The second guarded operation is activating a financing plan. Activation attaches the plan to its project and recomputes credit attribution, bumping the project version; if a different draft plan for the same project was activated first and legitimately became the attached plan, a later activation carrying the previously observed `expected_project_version` is rejected, resolving which draft plan binds to a project against the snapshot the client observed. Endpoints not named here take no version field.

### 2.9. Validation Ordering

When several checks guard a single endpoint, they are evaluated in a fixed precedence so that the returned error is deterministic. Authentication (`ERR_UNAUTHENTICATED`) is checked first, then role authorization (`ERR_FORBIDDEN_ROLE`), then existence of every path- and body-referenced resource validated left-to-right (`ERR_NOT_FOUND`), then resource ownership for entity-backed callers (`ERR_NOT_RESOURCE_OWNER`), then whether the target is in a state from which the requested transition is defined (`ERR_INVALID_STATE`). Only after these structural gates pass does the system evaluate domain-specific business rules, and finally body well-formedness for create endpoints (`ERR_INVALID_REQUEST`, HTTP 400) — malformed or missing required fields, out-of-range enums, and negative numerics. Within a single endpoint the structural order above always holds; the business checks specific to each endpoint are described alongside their workflows in Section 3.

## 3. Business Logic & Workflows

### 3.1. Registration and the Participants

Before any project exists, the participants register. A homeowner account captures an `email` that serves as a unique, non-empty login identifier across all homeowners, a `full_name`, a two-letter uppercase `state_code` drawn from the set `CA`, `NJ`, `MA`, `TX`, and `AZ`, and the homeowner's prior twelve-month electricity consumption `annual_kwh_usage` in kilowatt-hours, which must be zero or greater and later drives design sizing. The `state_code` is consequential: it selects both the certificate market the system will trade in and the tax-credit rules that apply.

A solar installer registers with a `company_name` and a non-empty `licensed_states` array, each element of which must be one of the five recognized state codes. An SREC broker registers with a `firm_name`, a `broker_fee_pct` expressed as a fraction of gross proceeds between 0.0 and 0.25 inclusive, and a non-empty `operating_states` array of recognized state codes naming the certificate markets the broker trades. Utilities are registered by the operator rather than self-service: each carries a `name`, a two-letter `state_code` it serves, a `feeder_headroom_kw` of remaining export capacity that must be zero or greater, a `net_metering_rate_cents_per_kwh` retail credit rate, and an `export_credit_ratio` between 0.0 and 1.0 that defaults to 1.0 when omitted. A ratio of 1.0 means full retail net metering; any value below 1.0 means net billing, and as Section 3.7 explains, this single field forks the settlement math.

Registration endpoints are the only operations an `Anonymous` caller may invoke. Utility registration is reserved for `PlatformAdmin`.

### 3.2. From Request through Design

A `Homeowner` opens a project by submitting `homeowner_id` and the usable `roof_area_sqft`, an integer of zero or greater that ultimately caps system size. The project is born in `REQUESTED` status with an empty `installer_id`, and all of its computed economics — `system_size_kw`, `estimated_annual_production_kwh`, `gross_system_cost_cents`, `itc_credit_cents`, `financing_plan_id`, and `lifetime_srec_count` — start at their zero or null defaults until later stages fill them in.

The first transition is the **sunlight assessment**, performed by a `SolarInstaller`, which advances the project from `REQUESTED` to `ASSESSED`. The installer supplies a `shading_factor`, the fraction of irradiance lost to shading, which must lie between 0.0 and 1.0 inclusive, and `peak_sun_hours`, the average daily peak sun hours at the site, which must be zero or greater; both are written onto the project. An assessment attempted on a project not in `REQUESTED` is rejected as an invalid state.

**Design** advances the project from `ASSESSED` to `DESIGNED` and is the moment the system's physical and financial shape is fixed. The acting `SolarInstaller` supplies its `installer_id` and the turnkey `gross_system_cost_cents` (integer cents, zero or greater), and the system records the installer on the project. Three preconditions guard design beyond the state check: the acting installer must be licensed in the homeowner's state — that is, the homeowner's `state_code` must appear in the installer's `licensed_states`, failing which the request is rejected with `ERR_INSTALLER_NOT_LICENSED` (HTTP 422); the `roof_area_sqft` must be greater than zero; and the assessment must leave system size well-defined. If `peak_sun_hours` is zero, or if the shading factor is exactly 1.0 (leaving no usable irradiance), system size is undefined and the request is rejected with `ERR_DESIGN_INFEASIBLE` (HTTP 422).

When design succeeds, three figures are computed and pinned onto the project, described in Sections 3.3 and 3.4: the DC system size, the year-one production estimate, and the Federal tax credit. The project's `version` increments by one. A homeowner may cancel a project while it is still in `REQUESTED`, `ASSESSED`, or `DESIGNED` (see Section 3.6); cancellation is the homeowner's only write privilege over the project's progression and requires the acting homeowner to own the project.

### 3.3. Sizing the System and Estimating Production

System sizing picks the smaller of two caps so the array never exceeds either the roof or the household's needs. The **area cap** in kilowatts is the roof area divided by the constant seventy square feet per kilowatt; that quotient is truncated toward zero to two decimal places. The **usage target** in kilowatts is the homeowner's `annual_kwh_usage`, multiplied by a usage-offset factor of 1.0, divided by the product of `peak_sun_hours`, three hundred sixty-five days, and the quantity one minus the `shading_factor`; this result is likewise truncated toward zero to two decimal places. The pinned `system_size_kw` is the smaller of the area cap and the usage target. If `peak_sun_hours` is zero or the quantity one minus the shading factor is zero, the usage target is undefined and design is rejected as infeasible, as noted above.

The year-one production estimate follows directly. The `estimated_annual_production_kwh` is the `system_size_kw` multiplied by `peak_sun_hours`, by three hundred sixty-five days, by the quantity one minus the `shading_factor`, and by a system-derate factor of 0.80, with the final product rounded half up to a whole kilowatt-hour. This estimate becomes the anchor for warranty production guarantees and for power-purchase-agreement pricing later on.

### 3.4. The Federal Tax Credit and Its Attribution

The Federal Investment Tax Credit is computed at design time and stored as `itc_credit_cents`. The base rate is thirty percent. Certain states carry a domestic-content or energy-community adder layered on top: New Jersey, Massachusetts, and Arizona each add ten percentage points, while California and Texas add nothing. The effective rate is the base rate plus the state's adder, but never more than the forty-percent cap. The credit in cents is the `gross_system_cost_cents` multiplied by that effective rate, rounded half up to whole cents.

Who actually books that credit is not settled at design — it is provisionally attributed to the project pending financing and only resolved when a financing plan activates. The `itc_beneficiary` is determined by the financing model: under a `LOAN`, the homeowner books the credit, so the beneficiary is `HOMEOWNER`; under a `PPA` or a `LEASE`, the third-party financier owns the system and books the credit, so the beneficiary is `FINANCIER` and the homeowner receives none. Activation recomputes this attribution onto the project (see Section 3.5).

### 3.5. Choosing and Activating Financing

A `Homeowner` creates a financing plan for a designed project by supplying the `project_id`, the `model` — one of `PPA`, `LEASE`, or `LOAN` — and a `term_years` between 1 and 25 inclusive. The plan is born in `DRAFT` status. The model dictates which additional fields are required, and the system rejects a create that omits the model-specific fields with `ERR_FINANCING_FIELDS_MISSING` (HTTP 422): a `PPA` requires both `ppa_rate_cents_per_kwh` (the energy price in cents per kilowatt-hour, zero or greater) and `ppa_escalator_pct` (the annual escalator as a fraction between 0.0 and 0.10 inclusive); a `LEASE` requires `lease_monthly_cents` (a fixed monthly payment in cents, zero or greater); a `LOAN` requires `loan_principal_cents` (the principal in cents, zero or greater) and `loan_apr` (the nominal annual rate as a fraction between 0.0 and 0.30 inclusive). Fields belonging to a model other than the one chosen are ignored.

At creation the system also pins `srec_owner` and `itc_beneficiary` from the model: a `LOAN` sets both to `HOMEOWNER`, while a `PPA` or `LEASE` sets both to `FINANCIER`. These two enumerated fields therefore travel together and always agree under the same model.

**Activation**, performed by the owning `Homeowner`, moves the plan from `DRAFT` to `ACTIVE`. It requires the plan to be a draft, the plan's project to be in `DESIGNED` status, and the acting homeowner to own that project. Activation carries `expected_project_version` and is rejected with `ERR_STALE_PROJECT_VERSION` (HTTP 412) if it does not match the project's current `version`, as Section 2.8 describes. A project may hold at most one non-terminated financing plan; an attempt to activate a second plan while one is already active is rejected with `ERR_FINANCING_ALREADY_ACTIVE` (HTTP 409). On success, the system computes the plan's `monthly_payment_cents`, sets the project's `financing_plan_id` to this plan, recomputes the project's `itc_credit_cents` attribution per the model, increments the project's `version` by one as a derived-field reconciliation, and increments the plan's own `version` by one.

The level **monthly payment** depends on the model. For a `LEASE` it is simply the `lease_monthly_cents`, a flat contractual amount independent of production. For a `LOAN` it is a standard amortization over the term: let the monthly rate be the `loan_apr` divided by twelve and the number of payments be the `term_years` multiplied by twelve; when the monthly rate is zero, the payment is the `loan_principal_cents` divided by the number of payments, rounded half up; otherwise the payment is the principal multiplied by the annuity factor, where that factor is the monthly rate times the quantity one plus the monthly rate raised to the number of payments, all divided by the quantity one plus the monthly rate raised to the number of payments minus one, again rounded half up. For a `PPA`, the year-one monthly payment is an estimate derived from production with the escalator ignored in the first year: take the project's `estimated_annual_production_kwh` multiplied by `ppa_rate_cents_per_kwh` to get the annual figure, divide by twelve, and round half up. All three results are whole cents.

### 3.6. Permitting, Installation, Inspection, and Permission to Operate

Once a financing plan is active, the project advances toward construction. The `SolarInstaller` **submits the permit package**, moving the project from `DESIGNED` to `PERMIT_PENDING`; this requires that the project carry a non-null `financing_plan_id` whose plan is in `ACTIVE` status. A `PlatformAdmin` then **approves the permit**, moving it from `PERMIT_PENDING` to `PERMIT_APPROVED`. The installer **completes the install**, moving it from `PERMIT_APPROVED` to `INSTALLED`; the acting installer must be the one recorded on the project.

A `PlatformAdmin` then **inspects** the installed system, supplying a `result`. A passing inspection advances the project from `INSTALLED` to `PTO_PENDING`; a failing inspection sends it from `INSTALLED` to `FAILED_INSPECTION`. From a failure the assigned installer **begins remediation**, moving `FAILED_INSPECTION` to `REMEDIATION`, and then **completes the install** again to return `REMEDIATION` to `INSTALLED`, re-entering the inspection branch. This remediation loop may cycle until an inspection passes; each completion of the install from remediation requires the acting installer to be the project's recorded installer.

**Permission to operate** is granted on the interconnection side and reaches across to the project. When a `Utility` grants PTO on an application (Section 3.8) whose project is in `PTO_PENDING`, the project transitions to `OPERATIONAL` — a terminal state — and a `WarrantyPolicy` is minted for it with `coverage_start` set to the grant time and `coverage_years` of 25. Both the application and the project have their `version` incremented.

A `Homeowner` who owns a project may **cancel** it while it remains in `REQUESTED`, `ASSESSED`, or `DESIGNED`. Cancellation moves the project to the terminal `CANCELLED` state, increments its `version`, and — if the project already has an attached financing plan — cascades that plan to `TERMINATED`, incrementing the plan's `version` as well. A plan in either `DRAFT` or `ACTIVE` status is terminated by this cascade; the cascade only fires while the project is still in a cancellable state.

### 3.7. Interconnection Review and the Feeder-Capacity Ledger

A `SolarInstaller` files an **interconnection application** by supplying the `project_id`, the reviewing utility's `utility_id`, and the `requested_export_kw` grid-export capacity (zero or greater). The application is born in `FILED` status. The reviewing `Utility` — and only the utility named on the application — then drives the review: it **begins review**, moving `FILED` to `UNDER_REVIEW`.

From under review the utility may **approve** or **reject**. Approval, moving `UNDER_REVIEW` to `APPROVED`, is a safety-gated ledger operation: it is permitted only when the utility's `feeder_headroom_kw` is at least the application's `requested_export_kw`, failing which it is rejected with `ERR_INSUFFICIENT_FEEDER_HEADROOM` (HTTP 422). On approval the utility's `feeder_headroom_kw` is decremented by the `requested_export_kw`, and both the utility's and the application's `version` increment. Rejection, moving `UNDER_REVIEW` to the terminal `REJECTED` state, simply increments the application's `version`.

An already-approved application may be **withdrawn** — moving `APPROVED` to `REJECTED` — but only while its project has not yet reached `OPERATIONAL`. Withdrawal is the compensating action for approval: it restores the utility's `feeder_headroom_kw` by exactly the `requested_export_kw` the approval decremented, conserving total feeder capacity, and increments both the utility's and the application's `version`. Finally, **granting PTO** moves an `APPROVED` application to the terminal `PTO_GRANTED` state, but only when its project is in `PTO_PENDING`; as Section 3.6 noted, this same operation drives the project to `OPERATIONAL` and mints the warranty policy.

### 3.8. Net Metering and the kWh Bank

Once a project is operational, the serving `Utility` records monthly **net-meter periods** and settles them in order. Creating a period supplies the `project_id`, the inclusive `period_start` and exclusive `period_end` (the end must be strictly after the start, else `ERR_INVALID_INTERVAL`, HTTP 422), and the metered `kwh_produced` and `kwh_consumed`, each a whole number of zero or greater. Periods are born `OPEN`. Two periods on the same project may not overlap: intervals are half-open `[period_start, period_end)`, so a new period whose half-open span intersects any existing period on the project is rejected with `ERR_PERIOD_OVERLAP` (HTTP 409), though periods that merely touch at an endpoint are allowed.

**Settlement** moves a period from `OPEN` to `SETTLED` and must proceed in chronological `period_start` order: settling a period while an earlier `OPEN` period still exists on the same project is rejected with `ERR_OUT_OF_ORDER_SETTLEMENT` (HTTP 409). Settlement computes three derived fields. The `net_kwh` is the `kwh_produced` minus the `kwh_consumed`, a signed quantity. The project carries a kilowatt-hour bank that starts at zero for the first period and carries forward; `bank_kwh_after` is the bank balance once this period is settled.

When `net_kwh` is zero or positive, the period exported a surplus. The credited kilowatt-hours equal the surplus floored to a whole number, and the `bill_credit_cents` is that credited figure multiplied by the utility's `net_metering_rate_cents_per_kwh` and by the utility's `export_credit_ratio`, rounded half up. The `bank_kwh_after` grows by the full surplus over the prior bank balance. When `net_kwh` is negative, the period ran a deficit equal to the negated `net_kwh`. The system first draws from the bank: the drawn amount is the smaller of the prior bank balance and the deficit, the `bank_kwh_after` is the prior balance minus that draw, and the billable remainder is the deficit minus the draw. The `bill_credit_cents` is then the negative of the billable kilowatt-hours multiplied by the `net_metering_rate_cents_per_kwh`, rounded half up — a negative value representing a charge. The `export_credit_ratio` is the fork between the two variants: at a ratio of 1.0 the surplus is credited at the full retail rate, symmetric with the consumption charge (full retail net metering); below 1.0 the surplus is credited at a discounted rate while consumption is still charged at full retail, an asymmetric net-billing outcome that yields a different `bill_credit_cents` for the same `net_kwh`. After settlement, `bank_kwh_after` becomes the bank baseline carried into the next period.

### 3.9. Minting, Listing, and Selling Certificates

A `PlatformAdmin` **mints** a Solar Renewable Energy Certificate against an operational project by supplying the `project_id` and the `vintage_year` (the calendar year the underlying generation occurred, 2020 or later). Each certificate is born `MINTED`. Its `owner_type` is copied from the financing plan's `srec_owner` — `HOMEOWNER` under a loan, `FINANCIER` under a PPA or lease. Minting increments the project's `lifetime_srec_count` — the running count of certificates ever minted for that project — and the project's `version`. The certificate's `srec_sale_id` is null until it is sold, and its `created_at` mint timestamp serves as the chronological tie-break for sale batching.

The owning `Homeowner` **lists** a certificate for sale, moving it from `MINTED` to `LISTED`, which requires the certificate's project to be `OPERATIONAL`. An `SrecBroker` then **creates a sale** that sweeps a pool. The sale supplies the `project_id`, the buying `broker_id`, the `vintage_year` filter, the offered `price_cents_per_srec` (zero or greater), and the `expected_project_version` for the optimistic-concurrency guard described in Section 2.8. The broker must trade the homeowner's market — the homeowner's `state_code` must appear in the broker's `operating_states`, else `ERR_BROKER_MARKET_MISMATCH` (HTTP 422). The sweep gathers every certificate of the named project and vintage whose status is `LISTED`; if no such certificate exists the sale is rejected with `ERR_NO_LISTED_SRECS` (HTTP 422).

Settlement of the sale processes the swept certificates in chronological mint order by their `created_at`. The `srec_count` is the number swept. The `gross_proceeds_cents` is that count multiplied by the `price_cents_per_srec`. The broker fee is computed on the gross total — not per certificate — as the `gross_proceeds_cents` multiplied by the broker's `broker_fee_pct`, rounded half up; the `net_proceeds_cents` is the gross proceeds minus that fee. This sum-then-round ordering is pinned: the fee is taken once against the total. Each swept certificate moves from `LISTED` to `SOLD`, has its `srec_sale_id` set to the new sale, and has its `version` incremented; the project's `version` also increments. Afterward, the buying broker may **retire** a sold certificate, moving it from `SOLD` to the terminal `RETIRED` state.

### 3.10. Warranty Claims and Production Shortfall

The warranty policy minted at operational time records a `production_guarantee_pct` — the guaranteed fraction of `estimated_annual_production_kwh` below which a production claim is honored, greater than zero and at most 1.0 — a `coverage_start`, and a `coverage_years` fixed at 25. Against an operational project, the owning `Homeowner` **files a warranty claim** with the `project_id` and a `claim_type` of either `PRODUCTION_SHORTFALL` or `EQUIPMENT_DEFECT`. A production-shortfall claim also supplies a `claimed_window_start` and `claimed_window_end` describing the twelve-month production window it measures; the end must be strictly after the start (`ERR_INVALID_INTERVAL`, HTTP 422), and these fields are ignored for an equipment-defect claim. Claims are born `SUBMITTED`.

A production-shortfall claim's `[claimed_window_start, claimed_window_end]` window must not collide with any non-denied production-shortfall claim already on the same project, evaluated with closed-interval semantics: two windows conflict whenever the first window's start is at or before the second window's end and the second window's start is at or before the first window's end — so windows that merely share an endpoint do collide, unlike the half-open rule for net-meter periods. A colliding window is rejected with `ERR_CLAIM_WINDOW_OVERLAP` (HTTP 409).

Adjudication is the `SolarInstaller`'s job. The installer may **request information**, moving a `SUBMITTED` claim to `INFO_REQUESTED`; the owning homeowner then **resubmits**, moving `INFO_REQUESTED` back to `SUBMITTED` in a cyclic revision loop. The installer may **deny** a `SUBMITTED` claim, moving it to the terminal `DENIED` state, or **approve** it, moving `SUBMITTED` to `APPROVED`. Approval requires the claim's project to be `OPERATIONAL` and, for a production-shortfall claim, a positive shortfall after evaluation; a zero shortfall cannot be approved and is rejected with `ERR_NO_SHORTFALL` (HTTP 422). On approval the system evaluates and pins three fields. The `measured_production_kwh` is the sum of `kwh_produced` across the project's `SETTLED` net-meter periods whose `period_start` is at or after the window start and whose `period_end` is at or before the window end; for an equipment-defect claim it is zero. The guaranteed figure is the project's `estimated_annual_production_kwh` multiplied by the policy's `production_guarantee_pct`, floored to a whole kilowatt-hour. The `shortfall_kwh` is the larger of zero and the guaranteed figure minus the measured production. The `payout_cents` values that shortfall at the project's net-metering retail rate — the `net_metering_rate_cents_per_kwh` of the utility on its interconnection — as the `shortfall_kwh` multiplied by that rate, rounded half up. Finally the installer may **remediate** an `APPROVED` claim, moving it to the terminal `REMEDIATED` state. Each claim transition increments the claim's `version`.

## 4. Endpoint Definitions

All endpoints share the response envelope of Section 2.2. Creating a new resource returns HTTP 201; reads and state-changing operations on an existing resource return HTTP 200. Request and response bodies are not repeated here; reconstruct them from the workflows in Section 3.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | /solar/homeowners | Register a homeowner | Anonymous |
| GET | /solar/homeowners/{id} | Fetch a homeowner | Homeowner, PlatformAdmin |
| POST | /solar/installers | Register a solar installer | Anonymous |
| GET | /solar/installers/{id} | Fetch an installer | SolarInstaller, PlatformAdmin |
| POST | /solar/utilities | Register a utility | PlatformAdmin |
| GET | /solar/utilities/{id} | Fetch a utility | Utility, PlatformAdmin |
| POST | /solar/brokers | Register an SREC broker | Anonymous |
| GET | /solar/brokers/{id} | Fetch a broker | SrecBroker, PlatformAdmin |
| POST | /solar/projects | Create a project request | Homeowner |
| GET | /solar/projects/{id} | Fetch a project | Homeowner, SolarInstaller, PlatformAdmin, Utility |
| GET | /solar/projects | List projects (filter by homeowner_id, installer_id, financing_plan_id) | Homeowner, SolarInstaller, PlatformAdmin |
| POST | /solar/projects/{id}/assess | Record sunlight assessment | SolarInstaller |
| POST | /solar/projects/{id}/design | Submit design; compute size, production, ITC | SolarInstaller |
| POST | /solar/projects/{id}/submit-permit | Submit permit package | SolarInstaller |
| POST | /solar/projects/{id}/approve-permit | Approve permit | PlatformAdmin |
| POST | /solar/projects/{id}/complete-install | Mark install complete | SolarInstaller |
| POST | /solar/projects/{id}/inspect | Record inspection (pass or fail) | PlatformAdmin |
| POST | /solar/projects/{id}/start-remediation | Begin remediation | SolarInstaller |
| POST | /solar/projects/{id}/cancel | Cancel a project; cascade plan termination | Homeowner |
| POST | /solar/financing-plans | Create a DRAFT financing plan | Homeowner |
| GET | /solar/financing-plans/{id} | Fetch a financing plan | Homeowner, PlatformAdmin |
| GET | /solar/financing-plans | List financing plans (filter by project_id) | Homeowner, PlatformAdmin |
| POST | /solar/financing-plans/{id}/activate | Activate a DRAFT plan; OCC on project version | Homeowner |
| POST | /solar/interconnection-applications | File an interconnection application | SolarInstaller |
| GET | /solar/interconnection-applications/{id} | Fetch an interconnection application | SolarInstaller, Utility, PlatformAdmin |
| GET | /solar/interconnection-applications | List applications (filter by project_id, utility_id) | SolarInstaller, Utility, PlatformAdmin |
| POST | /solar/interconnection-applications/{id}/begin-review | Begin utility review | Utility |
| POST | /solar/interconnection-applications/{id}/approve | Approve interconnection; decrement feeder headroom | Utility |
| POST | /solar/interconnection-applications/{id}/reject | Reject interconnection | Utility |
| POST | /solar/interconnection-applications/{id}/withdraw | Withdraw an approved interconnection; restore headroom | Utility |
| POST | /solar/interconnection-applications/{id}/grant-pto | Grant PTO; drive project operational and mint warranty | Utility |
| POST | /solar/srecs | Mint an SREC for an operational project | PlatformAdmin |
| GET | /solar/srecs/{id} | Fetch an SREC | Homeowner, SrecBroker, PlatformAdmin |
| GET | /solar/srecs | List SRECs (filter by project_id, srec_sale_id, status) | Homeowner, SrecBroker, PlatformAdmin |
| POST | /solar/srecs/{id}/list | List an SREC for sale | Homeowner |
| POST | /solar/srecs/{id}/retire | Retire a sold SREC | SrecBroker |
| POST | /solar/srec-sales | Create a sweep sale; OCC on project version | SrecBroker |
| GET | /solar/srec-sales/{id} | Fetch an SREC sale | SrecBroker, Homeowner, PlatformAdmin |
| GET | /solar/srec-sales | List SREC sales (filter by project_id, broker_id) | SrecBroker, Homeowner, PlatformAdmin |
| POST | /solar/net-meter-periods | Open a billing-month period | Utility |
| GET | /solar/net-meter-periods/{id} | Fetch a net-meter period | Utility, Homeowner, PlatformAdmin |
| GET | /solar/net-meter-periods | List net-meter periods (filter by project_id, status) | Utility, Homeowner, PlatformAdmin |
| POST | /solar/net-meter-periods/{id}/settle | Settle a period in chronological order | Utility |
| GET | /solar/warranty-policies/{id} | Fetch a warranty policy | Homeowner, SolarInstaller, PlatformAdmin |
| GET | /solar/warranty-policies | List warranty policies (filter by project_id) | Homeowner, SolarInstaller, PlatformAdmin |
| POST | /solar/warranty-claims | File a warranty claim | Homeowner |
| GET | /solar/warranty-claims/{id} | Fetch a warranty claim | Homeowner, SolarInstaller, PlatformAdmin |
| GET | /solar/warranty-claims | List warranty claims (filter by project_id, status) | Homeowner, SolarInstaller, PlatformAdmin |
| POST | /solar/warranty-claims/{id}/request-info | Request more info | SolarInstaller |
| POST | /solar/warranty-claims/{id}/resubmit | Resubmit after info request | Homeowner |
| POST | /solar/warranty-claims/{id}/approve | Approve claim; evaluate shortfall and payout | SolarInstaller |
| POST | /solar/warranty-claims/{id}/deny | Deny claim | SolarInstaller |
| POST | /solar/warranty-claims/{id}/remediate | Mark claim remediated | SolarInstaller |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| --- | --- |
| ERR_UNAUTHENTICATED | 401 |
| ERR_FORBIDDEN_ROLE | 403 |
| ERR_NOT_RESOURCE_OWNER | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_INVALID_STATE | 409 |
| ERR_INSTALLER_NOT_LICENSED | 422 |
| ERR_DESIGN_INFEASIBLE | 422 |
| ERR_FINANCING_FIELDS_MISSING | 422 |
| ERR_FINANCING_ALREADY_ACTIVE | 409 |
| ERR_PERIOD_OVERLAP | 409 |
| ERR_INVALID_INTERVAL | 422 |
| ERR_CLAIM_WINDOW_OVERLAP | 409 |
| ERR_OUT_OF_ORDER_SETTLEMENT | 409 |
| ERR_INSUFFICIENT_FEEDER_HEADROOM | 422 |
| ERR_NO_LISTED_SRECS | 422 |
| ERR_BROKER_MARKET_MISMATCH | 422 |
| ERR_NO_SHORTFALL | 422 |
| ERR_STALE_PROJECT_VERSION | 412 |
| ERR_INVALID_REQUEST | 400 |
