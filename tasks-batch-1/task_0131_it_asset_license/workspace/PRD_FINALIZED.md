# IT Asset & License API — Product Requirements Document

## 1. Introduction

Enterprises accumulate two intertwined kinds of property that rarely live in the same system of record: physical hardware on the one hand — laptops, desktops, servers, monitors, and mobile devices that are bought, assigned to staff, repaired, and eventually retired — and software entitlements on the other, where what is purchased is not a thing but a *right to install* up to a contracted number of seats or processor cores. The IT Asset & License API unifies the two into a single ledger-reconciled inventory. It tracks a hardware asset from the day it enters service, through every checkout to an employee and every repair cycle, down to the moment it is disposed of and its remaining book value is settled against the proceeds of sale. In parallel, it tracks each software product's purchased entitlement pool and continuously reconciles that pool against the installs actually charged to it, so that compliance officers always know whether the organization is within its license grant or over-deployed.

The central discipline this system enforces is **true-up**: the periodic reconciliation of entitled capacity against consumed capacity, run in two deliberately different variants — a *live* view that reflects only what is active right now, and an *audit* view that is stricter about what counts as consumed and more generous about what counts as still-entitled. Around that core sit the supporting lifecycles: straight-line depreciation that is booked provisionally on every read but finalized differently at disposal; warranty and lease coverage whose expiry is driven by a server-controlled clock; renewals that extend either an entitlement or a coverage in place; and a segregation-of-duties control on disposal, where the manager who proposes retiring an asset can never be the officer who approves it. Every time-dependent rule in this document reads a server wall clock rather than real elapsed time, so that depreciation as-of dates, coverage and term boundaries, and checkout intervals are all deterministic and test-controllable.

This document specifies the complete contract: the global envelope and access-control rules in Section 2, the business workflows and their scattered logic in Section 3, the endpoint surface in Section 4, and the error catalogue in Section 5.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelopes, and cross-cutting principles that govern every endpoint.

### 2.1. User and Role-Based Access Control

Every request to the API must carry two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the operational capacity in which that user acts. The system recognizes exactly three roles: `AssetManager`, `ComplianceOfficer`, and `Employee`. A request that omits either header, or whose `X-User-Role` is not one of these three values, is rejected with `ERR_UNAUTHENTICATED`. A request whose role is well-formed but not permitted to perform the requested operation, according to the authorization table in Section 4, is rejected with `ERR_FORBIDDEN`.

The three roles map to identity in different ways. When `X-User-Role` is `AssetManager`, `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity; the server records it where a workflow demands it — for instance, it is written into `submitted_by_user_id` on a `DisposalRequest` at submission time — but it is never compared against any entity's `id`. When `X-User-Role` is `ComplianceOfficer`, `X-User-ID` is likewise an opaque operator identifier not backed by any stored entity; the server records it where a transition writes it — for instance, into `approved_by_user_id` on a `DisposalRequest` at approval time — but does not equate it to any entity's `id`. The single comparison the system *does* make between these two opaque identifiers is the segregation-of-duties check on disposals, described in Section 3. When `X-User-Role` is `Employee`, by contrast, `X-User-ID` is the `id` of the acting `Employee` entity; ownership checks on any resource that references an employee compare that resource's employee foreign key to `X-User-ID`. The `Employee` role is read-only and may not perform any mutating operation.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10 when omitted, may be no smaller than 1, and may be no larger than 100. The `offset` parameter is the number of items to skip from the front of the result set and defaults to 0.

Unless a specific endpoint says otherwise, every list endpoint returns its resources sorted by creation timestamp (`created_at`) in ascending order. The response envelope's `meta` object for any list carries the four pagination fields `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. The Server Clock and Time-Dependent Evaluation

Time in this system is not real wall-clock time. A dedicated administrative capability sets the logical server clock to a supplied instant, and from that point forward every time-dependent rule reads that clock. Depreciation as-of dates, warranty and lease expiry, entitlement term and grace boundaries, and checkout interval comparisons all resolve against the server clock rather than against the host's real time. The clock-setting capability accepts a single field, `to_iso8601`, the ISO 8601 UTC instant the clock should advance to, and is available to both the `AssetManager` and the `ComplianceOfficer` roles. Setting the clock does not eagerly rewrite stored records; instead, time-derived fields are recomputed lazily whenever the affected resource is next read or transitioned.

### 2.5. Common Resource Properties

Most resources in the system carry a common set of system-managed fields. Every such resource has an `id`, a server-minted UUID with no type prefix; a `created_at` timestamp, an ISO 8601 UTC instant with three fractional digits marking when it was first created; an `updated_at` timestamp of the same format marking the last time any of its properties changed; and a `version`, an integer that starts at 1 and increments by one on every mutation of the resource. The `version` field is the basis for the optimistic-concurrency protection described in Section 2.7.

One entity is deliberately leaner. A `ComplianceFinding` is an immutable audit record minted at true-up finalization and never subsequently changed; it therefore carries only `id` and `created_at`. It has no `updated_at` and no `version` field at all.

### 2.6. Derived-Field Reconciliation and Precision

Several fields are never written directly by clients — they are *derived* and the system keeps them consistent on every mutation that could affect them. On a hardware asset, `accumulated_depreciation_cents`, `net_book_value_cents`, and `support_status` are recomputed against the current server clock each time the asset is read, and `disposal_gain_loss_cents` is computed at disposal. On a license entitlement, `consumed_units` and `available_units` are recomputed whenever an install charged to it is activated or uninstalled. On an employee, `open_checkout_count` reflects the live number of open checkouts. On a software product, `compliance_status` reflects the verdict of the most recent finalized reconciliation touching it. Whenever such a derived field is recomputed as part of handling a request, the owning resource is treated as mutated: its `updated_at` is refreshed and its `version` increments.

All monetary quantities in the system are integer cents — there are no fractional-cent values. Where a calculation produces a non-integer intermediate (depreciation per month, a renewal line item), the system rounds **half up** to a whole number of cents. Crucially, rounding is applied at the point each calculation specifies and only there — for depreciation, exactly once to the accumulated total rather than per month; for renewals, to each line item before the lines are summed. Unit quantities (entitled, consumed, and required core units) are whole integers and are never rounded because they never go fractional after the per-install ceiling is applied.

### 2.7. Optimistic Concurrency Control on Entitlement Writes

Two operations consume or rebase a license entitlement's capacity in a way that depends on the client having an up-to-date view of that entitlement, and both are guarded by optimistic concurrency control keyed on the entitlement's `version`.

The first is creating an installation record. A create-installation request must include `expected_entitlement_version`, carrying the `version` of the target `LicenseEntitlement` the client last observed. If another writer has advanced that entitlement's `version` since the client read it — for example, by charging capacity through a different install — the stored `version` no longer matches the supplied `expected_entitlement_version`, and the create is rejected with `ERR_STALE_VERSION` (HTTP 412). This forces the client to re-read the entitlement, and its now-stale view of `available_units`, before charging the pool again. A successful create increments the entitlement's `version` by one.

The second is completing a renewal order whose `target_type` is `ENTITLEMENT`. That completion request must include `expected_entitlement_version` carrying the entitlement `version` the order was quoted against. If the entitlement's `version` has advanced since the quote — meaning the term and unit baseline the renewal priced no longer holds — completion is rejected with `ERR_STALE_VERSION` (HTTP 412), and the renewal must be re-quoted against the current entitlement. A successful entitlement-targeted completion increments the entitlement's `version` by one. Operations not named here take no version field and perform no such check.

### 2.8. Referential Resolution and Validation Ordering

Every request is screened through a fixed ladder of checks, and the *first* check that fails determines the error returned. Authentication comes first: a missing or unrecognized `X-User-Role`/`X-User-ID` yields `ERR_UNAUTHENTICATED` (401). Authorization is second: a role not permitted for the operation yields `ERR_FORBIDDEN` (403). Existence is third: every identifier in the URL path and every foreign-key identifier in the request body must resolve to an existing entity, validated left to right, and the first unresolved identifier yields `ERR_NOT_FOUND` (404). Request well-formedness is fourth: required fields must be present, enum values must be legal, numeric fields constrained to be non-negative must satisfy that constraint, and per-core fields must be consistent with the product's license model; a violation yields `ERR_INVALID_REQUEST` (422). Only after all four pass does the system evaluate state legality (fifth), then optimistic-concurrency staleness (sixth), then the domain-specific business rules. This ordering means that, for example, a stale-version conflict is never reported on a resource that does not exist, and a business-rule rejection never masks a malformed body.

The domain business rules themselves are layered by concern, and where several could apply to one operation they are evaluated in a stable order: safety and compliance controls first, then referential-state controls, then temporal-window controls, then uniqueness and capacity controls. Section 3 states, for each operation, exactly which rules guard it and in what relationship.

## 3. Business Logic & Workflows

### 3.1. Configuring the Inventory: Vendors, Employees, and Products

Before any asset or license exists, the inventory is seeded with its reference data, all owned by the `AssetManager`. A **vendor** is created with a legal `name`, a `vendor_type` that must be one of `HARDWARE`, `SOFTWARE`, or `BOTH`, and a `support_email`; an `active` flag may be supplied and defaults to true, marking whether new assets and products may still reference this vendor. An **employee** is created with a `full_name`, an `email`, and a `department` cost-center label; an optional `max_assigned_assets` cap may be supplied and defaults to 3, governing how many hardware checkouts the employee may hold open at once and which must be zero or greater. A new employee always begins life with `status` of `ACTIVE` and an `open_checkout_count` of 0. An employee's `email` must be unique among all employees that are not `OFFBOARDED`; a collision is rejected with `ERR_DUPLICATE_KEY`. An employee's `status` cycles among `ACTIVE`, `SUSPENDED`, and `OFFBOARDED` through a status-change operation supplying the desired `to_status`.

A **software product** records the `vendor_id` of its publisher, a `name`, and a `license_model` that is either `PER_SEAT` or `PER_CORE`; the model is fixed at creation and may never be changed. For per-core products, two further inputs shape the licensing math: `core_factor`, a per-core multiplier applied to a machine's physical cores that defaults to 1.0, must be zero or greater, and is ignored entirely for per-seat products; and `min_core_units`, the per-install minimum number of core units that must be licensed, which defaults to 1, must be at least 1, and is likewise ignored for per-seat products. Every new product starts with a `compliance_status` of `COMPLIANT`; that field is never set by the client directly and is later driven only by entitlement suspension and by finalized true-ups, as described below. Products can be listed and filtered by `vendor_id` or by `license_model`.

### 3.2. Hardware Assets: Service Life, Depreciation, and Support Coverage

A **hardware asset** enters the system through the manager with a `vendor_id`, an org-unique `asset_tag`, and a `category` that is one of `LAPTOP`, `DESKTOP`, `SERVER`, `MONITOR`, or `MOBILE`. Its acquisition cost is recorded in `purchase_cost_cents`, the instant it entered service in `in_service_date`, and three depreciation inputs round out the record: `useful_life_months`, the straight-line horizon in whole months that defaults to 36 and must be at least 1; `salvage_value_cents`, the residual floor below which book value never falls, which defaults to 0 and may not be negative nor exceed the purchase cost; and `physical_cores`, the CPU core count used by per-core licensing math, which defaults to 0 and may not be negative. The `asset_tag` must be unique among all assets that are not `DISPOSED`; a duplicate is rejected with `ERR_DUPLICATE_KEY`. A newly created asset has `status` of `IN_STOCK`, a `support_status` of `UNCOVERED`, and `disposal_proceeds_cents` of 0.

An asset's book value is computed by **straight-line depreciation** and reflected in two derived fields, `accumulated_depreciation_cents` and `net_book_value_cents`. The depreciable base is the purchase cost less the salvage value. The exact monthly depreciation is that base divided by the useful life in months, kept as an exact ratio with no rounding at this stage. For any read or recompute before disposal — the **provisional** view — the number of whole months elapsed is the count of complete months from the in-service date to the current server clock, never less than zero, and capped at the useful life in months; a partial final month is *floored away* and does not count. Accumulated depreciation is the exact monthly amount multiplied by that capped month count, with the half-up rounding to whole cents applied once to that product (never month by month), and then additionally clamped so it can never exceed the depreciable base. Net book value is the purchase cost minus accumulated depreciation, which by construction never drops below the salvage value. Both derived fields refresh on every read of the asset.

An asset moves between `IN_STOCK` and `IN_REPAIR` through a transition supplying `to_status`: a stock asset may go into repair, and an asset in repair may return to stock, but no other pairing of those two is legal, and attempting a transition from the wrong starting state yields `ERR_INVALID_STATE`. Coverage of the asset by warranty or lease drives its `support_status`, a derived field that resolves to `IN_WARRANTY`, `LEASED`, `OUT_OF_WARRANTY`, or `UNCOVERED` based on whether an active coverage record spans the current server clock and whether that coverage is a warranty or a lease. Only coverage records whose `status` is `ACTIVE` or `RENEWED` are considered when resolving support status; a `CANCELLED` or `EXPIRED` coverage is disregarded entirely. Among the considered records, if one whose window spans the current server clock is a warranty, the status is `IN_WARRANTY`; if such a spanning record is a lease, the status is `LEASED` (a warranty match takes precedence over a lease match when both span). If no considered record currently spans the clock but at least one `ACTIVE` or `RENEWED` coverage record exists on the asset, the status is `OUT_OF_WARRANTY`. If the asset has no `ACTIVE` or `RENEWED` coverage record at all, the status is `UNCOVERED`.

**Warranty and lease coverage** is recorded as a coverage record naming the covered asset via `hardware_asset_id`, the provider via `vendor_id`, a `coverage_type` of either `WARRANTY` or `LEASE`, and an inclusive `coverage_start` and `coverage_end` window. A `monthly_cost_cents` charge may be supplied (defaulting to 0, as warranties typically carry none) and must be non-negative, and an `auto_renew` flag (defaulting to false) marks whether the coverage may later be extended by a renewal. A coverage record's window may not overlap any already-`ACTIVE` or `RENEWED` coverage on the same asset. Two windows are considered to overlap only when the new `coverage_start` falls strictly before the existing `coverage_end` *and* the existing `coverage_start` falls strictly before the new `coverage_end`; that is, a shared endpoint touch (the new window starting exactly when an existing one ends, or ending exactly when an existing one begins) is treated as zero-gap adjacency and is permitted. Only a genuine interior overlap is rejected, with `ERR_COVERAGE_OVERLAP`. This overlap check is applied only when a coverage record is created; renewing a coverage extends its `coverage_end` without re-checking overlap. A new coverage starts `ACTIVE`, and creating it immediately recomputes the asset's `support_status`. Coverage may be force-expired or cancelled through a transition supplying `to_status`: cancelling an active coverage moves it to `CANCELLED`, and expiring it moves it to `EXPIRED` — but a force-expiry is only legal once the server clock has advanced strictly past the `coverage_end`; an attempt before then is rejected with `ERR_COVERAGE_NOT_ENDED`, and a transition attempted from a non-active coverage is rejected with `ERR_INVALID_STATE`. Both the cancel and expire transitions recompute the asset's `support_status` afterward. Independently of any explicit transition, when the asset's support status is recomputed and the server clock has moved past an active coverage's `coverage_end`, that coverage is treated as `EXPIRED` for support purposes.

### 3.3. Assigning Hardware: Checkouts and Their Limits

Hardware reaches an employee through a **checkout**. The manager checks out an in-stock asset to an employee by supplying the `employee_id`, a `checkout_at` start instant, and an `expected_return_at` planned-return instant; the latter is the exclusive upper bound of the interval the asset is considered occupied. Several conditions must all hold for the checkout to succeed. The asset must currently be `IN_STOCK`; if it is not, the request is rejected with `ERR_ASSET_NOT_AVAILABLE`. The target employee must be `ACTIVE`; a suspended or offboarded employee yields `ERR_EMPLOYEE_NOT_ACTIVE`. The employee's `open_checkout_count` must be strictly less than their `max_assigned_assets`; if accepting the checkout would not leave room — that is, the count is already at or above the cap — the request is rejected with `ERR_ASSIGNMENT_LIMIT_REACHED`. And the new occupied interval, taken as half-open from `checkout_at` up to but not including `expected_return_at`, must not overlap the interval of any existing open checkout on the same asset; an overlap is rejected with `ERR_CHECKOUT_OVERLAP`. When all conditions pass, a checkout record is created with `status` of `OPEN`, the employee's `open_checkout_count` is increased by one, and the asset moves to `ASSIGNED`.

A checkout in flight records its actual return instant in `returned_at`, which stays null while the checkout is `OPEN`. Returning a checkout is legal only while it is `OPEN` — otherwise `ERR_INVALID_STATE` — and on return the checkout's `status` becomes `RETURNED`, its `returned_at` is stamped with the server clock, the holding employee's `open_checkout_count` is decreased by one, and the asset returns to `IN_STOCK`. A checkout may instead be marked lost through a transition supplying `to_status` of `LOST`, again legal only from `OPEN`; this sets the checkout's `status` to `LOST`, stamps `returned_at` with the server clock, decreases the employee's `open_checkout_count` by one, and returns the asset to `IN_STOCK` so that it can subsequently be routed through disposal. Checkouts can be listed and filtered by `hardware_asset_id`, by `employee_id`, or by `status`; an `Employee` viewing the list sees their own checkouts, matched on their `employee_id`.

### 3.4. Entitlements and Installs: Charging the License Pool

A **license entitlement** is the purchased capacity against which installs are charged. The manager creates one naming the `software_product_id` it licenses and the `vendor_id` that sold it, the purchased `entitled_units` (seats for a per-seat product, core-units for a per-core product, never negative), the `unit_price_cents` that forms the renewal cost basis, an inclusive `term_start` and `term_end`, and an optional `grace_days` count (defaulting to 0, never negative) of days after the term ends during which the entitlement still counts toward audit reconciliation. A new entitlement is created in `DRAFT` with `consumed_units` of 0 and `available_units` equal to its entitled units. Activating it moves it from `DRAFT` to `ACTIVE`; activation requires that it currently be `DRAFT` (else `ERR_INVALID_STATE`) and that its term window be well-formed, with `term_start` no later than `term_end` — a reversed window is rejected with `ERR_INVALID_TERM_WINDOW`. Entitlements can be listed and filtered by `software_product_id`, `vendor_id`, or `status`.

An **installation record** ties a product to a machine and charges an entitlement. Creating one supplies the `software_product_id` being installed, the `hardware_asset_id` it is installed on, and the `license_entitlement_id` charged for it, along with the `expected_entitlement_version` that guards the create under optimistic concurrency (Section 2.7). At creation the install computes and freezes `required_core_units`, the number of units it will consume once active. For a per-seat product this is always exactly 1, regardless of the machine's core count. For a per-core product it is the larger of the product's `min_core_units` and the machine's physical core count multiplied by the product's `core_factor` and rounded up to the next whole number — the ceiling is applied to that product before the minimum floor is taken, and because `core_factor` may be fractional (such as 0.5 for hyperthread discounting) the ceiling matters. A new install is `PENDING` and consumes nothing yet; its `activated_at` is null until it is activated.

Activating an install is where capacity is actually charged. Activation requires the install to be `PENDING` (else `ERR_INVALID_STATE`); the charged entitlement to be `ACTIVE`, with a non-active entitlement rejected as `ERR_ENTITLEMENT_NOT_ACTIVE`; and the host asset to be in one of `IN_STOCK`, `ASSIGNED`, or `IN_REPAIR` — never `RETIRED` or `DISPOSED` — with an unavailable host rejected as `ERR_ASSET_NOT_AVAILABLE`. Finally, the entitlement's current `consumed_units` plus this install's `required_core_units` must not exceed its `entitled_units`; if charging this install would push consumption past the entitled pool, activation is rejected with `ERR_ENTITLEMENT_EXCEEDED`. On success the install becomes `ACTIVE`, its `activated_at` is stamped with the server clock, the entitlement's `consumed_units` is increased by this install's `required_core_units`, and its `available_units` is recomputed as entitled minus consumed (a value that may legitimately go negative when over-deployment has occurred through other paths). A pending install may instead be rejected through a transition supplying `to_status` of `REJECTED`, legal only from `PENDING`. An active install may be uninstalled through a transition supplying `to_status` of `UNINSTALLED`, legal only from `ACTIVE`; uninstalling decreases the entitlement's `consumed_units` by exactly the units that install had charged and recomputes `available_units`, so that the consumed total is conserved across the install-then-uninstall cycle. Installs can be listed and filtered by `software_product_id`, `hardware_asset_id`, `license_entitlement_id`, or `status`.

An entitlement's later life is governed by the compliance officer. Suspending an active entitlement moves it to `SUSPENDED` and, as a cascade up to its product, sets that `SoftwareProduct.compliance_status` to `UNDER_REVIEW`. Resuming a suspended entitlement moves it back to `ACTIVE` and re-baselines the product's `compliance_status` to `COMPLIANT`, a baseline that the next finalized true-up may again override. Force-expiring an entitlement is permitted from `ACTIVE` or `SUSPENDED` but only once the server clock has advanced strictly past its `term_end`; an attempt before then is rejected with `ERR_TERM_NOT_ENDED`, and a transition from any other state is rejected with `ERR_INVALID_STATE`. Expiry moves the entitlement to `EXPIRED` and cascades: every install currently `ACTIVE` and charged to that entitlement is moved to `UNINSTALLED`, each decrementing the entitlement's `consumed_units` by the units it had charged. All three of these officer-driven transitions are requested through the entitlement transition operation supplying the desired `to_status`.

### 3.5. Renewals: Extending Entitlements and Coverage in Place

A **renewal order** extends either a license entitlement or a warranty/lease coverage without creating a replacement record. The compliance officer creates one declaring a `target_type` of either `ENTITLEMENT` or `COVERAGE`. When the target is an entitlement, the order carries a `license_entitlement_id` and leaves `warranty_lease_id` null; when the target is coverage, it carries a `warranty_lease_id` and leaves `license_entitlement_id` null — exactly one of the two foreign keys is set. The order also specifies `extend_months`, the whole number of months (at least 1) by which the term or coverage end is pushed out on completion, and for entitlement targets an optional `added_units` count (defaulting to 0, never negative) of extra entitled units to grant. A new order is `QUOTED`, with `quoted_cost_cents` not yet computed.

Completing a quoted order is what applies the extension and is where the cost is computed. Completion requires the order to be `QUOTED` (else `ERR_INVALID_STATE`). For an entitlement target, the entitlement must be `ACTIVE` or `SUSPENDED`, and the completion must carry `expected_entitlement_version` matching the entitlement's current `version` per Section 2.7; on success the entitlement's `term_end` is advanced by `extend_months` months, its `entitled_units` is increased by `added_units`, its `available_units` is recomputed, and its `version` increments. The entitlement is marked `RENEWED` as the audit signal that a renewal occurred but immediately settles back to `ACTIVE` so that installs may continue to charge against it — this is the cyclic `ACTIVE → RENEWED → ACTIVE` pattern. For a coverage target, the coverage must be `ACTIVE` and its `auto_renew` flag must be true; a coverage that is not active or not auto-renew-eligible is rejected with `ERR_RENEWAL_NOT_ELIGIBLE`. On success the coverage's `coverage_end` is advanced by `extend_months` months, the asset's `support_status` is recomputed, and the coverage likewise passes through `RENEWED` and settles back to `ACTIVE`. In all cases the order itself becomes `COMPLETED`.

The renewal cost recorded in `quoted_cost_cents` depends on the target. For an entitlement target, the cost is the sum of two line items, each rounded to whole cents *before* they are added together: the first line is the existing `entitled_units` times the `unit_price_cents` times the fraction `extend_months` divided by 12, rounded half up; the second line is the `added_units` times the `unit_price_cents` times that same `extend_months`-over-12 fraction, rounded half up. This per-line rounding order is deliberate — summing the two un-rounded products and rounding once at the end can differ from the pinned result by a cent and is not the intended computation. For a coverage target, the cost is simply the coverage's `monthly_cost_cents` times `extend_months`, rounded half up. A quoted order that is no longer wanted may be cancelled through a transition supplying `to_status` of `CANCELLED`, legal only from `QUOTED`. Renewal orders can be listed and filtered by `license_entitlement_id`, `warranty_lease_id`, or `status`.

### 3.6. Disposal: Segregation of Duties, Settlement, and Reversal

Retiring and disposing of an asset is the system's most controlled workflow, deliberately split between two actors. An `AssetManager` opens the process by submitting a **disposal request** naming the `hardware_asset_id` proposed for retirement, a `reason` that is one of `END_OF_LIFE`, `DAMAGED`, `LOST`, or `SOLD`, and an optional `proposed_proceeds_cents` (defaulting to 0, never negative) recording the expected sale proceeds. On submission the request's `status` is `SUBMITTED`, and the submitting user's `X-User-ID` is captured into `submitted_by_user_id`. Requests can be listed and filtered by `hardware_asset_id` or `status`.

Approval is reserved to a `ComplianceOfficer`, and the cornerstone control is **segregation of duties**: the approving (or rejecting) officer's `X-User-ID` must differ from the request's `submitted_by_user_id`. If the same user who submitted attempts to approve or reject, the request is rejected with `ERR_SEGREGATION_OF_DUTIES`. Beyond that, approval requires the request to be `SUBMITTED` (else `ERR_INVALID_STATE`); the asset to be retireable, meaning its status is `IN_STOCK` or `IN_REPAIR`, with any other status rejected as `ERR_ASSET_NOT_RETIREABLE`; and the asset to have no open checkout, with an outstanding open checkout rejected as `ERR_ASSET_HAS_OPEN_CHECKOUT`. Among these, the segregation-of-duties control and the open-checkout safety control take precedence over the retireability check in the layering described in Section 2.8. On approval the officer's `X-User-ID` is written to `approved_by_user_id`, the request moves to `APPROVED`, and the asset is moved to `RETIRED` as the first cascade hop. Rejecting a submitted request — also subject to the segregation-of-duties rule and legal only from `SUBMITTED` — simply moves the request to `REJECTED`, which is terminal.

Completing an approved request is what actually disposes the asset and settles its books. Completion requires the request to be `APPROVED` and the asset to be `RETIRED` (either condition failing yields `ERR_INVALID_STATE`). On completion the asset transitions from `RETIRED` to `DISPOSED`, and a sequence of settlements fires atomically. Depreciation is finalized as of the server clock using the **disposal variant**, which differs from the provisional book view in exactly one respect: a partial final month is counted as a *whole* month — rounded up rather than floored — though still capped at the useful life in months. Because a mid-month disposal therefore books one additional month of depreciation compared with the provisional floor, identical inputs yield a different `accumulated_depreciation_cents` and `net_book_value_cents` at disposal than a pre-disposal read would have shown. The asset's `net_book_value_cents` is recomputed on that final basis; its `disposal_proceeds_cents` is set to the request's `proposed_proceeds_cents`; and its `disposal_gain_loss_cents` is computed as the disposal proceeds minus that net book value at disposal, a signed figure where a positive result is a gain and a negative result a loss. As a further cascade, every install still `ACTIVE` on the disposed asset is moved to `UNINSTALLED`, each releasing its charged units back to its entitlement's ledger. Finally the request's `status` becomes `COMPLETED`.

A completed disposal can be undone by a **reversal**, a compensating action available to the compliance officer. Reversal requires the request to be `COMPLETED` and the asset to be `DISPOSED` (either failing yields `ERR_INVALID_STATE`). It zeroes the asset's `disposal_proceeds_cents` and `disposal_gain_loss_cents`, recomputes `accumulated_depreciation_cents` and `net_book_value_cents` from the server clock on the provisional basis to restore the pre-disposal book value, returns the asset from `DISPOSED` to `RETIRED`, and marks the request `REVERSED`. One asymmetry is intentional: the installs that the disposal cascade uninstalled are *not* resurrected. The compensation conserves the asset's total net book value, not the install graph, so any software that was uninstalled at disposal must be re-installed explicitly if needed.

### 3.7. True-Up Reconciliation and Compliance Findings

The compliance heart of the system is **true-up reconciliation**, which compares a software product's entitled capacity against its consumed capacity and renders a verdict. A `ComplianceOfficer` opens a reconciliation naming the `software_product_id` to reconcile and a `variant` of either `LIVE` or `AUDIT`; an `as_of` instant may be supplied and, when omitted, defaults to the current server clock. The reconciliation is created in `DRAFT` and computes nothing until it is finalized.

The two variants deliberately draw different boundaries around what counts. Under the **live** variant, the entitlements in scope for the product are those whose `status` is `ACTIVE` and whose term spans the as-of instant — that is, `term_start` is on or before the as-of instant and the as-of instant is on or before `term_end`. The installs in scope under the live variant are those whose `status` is `ACTIVE`. Under the **audit** variant, the entitlements in scope are those whose `status` is `ACTIVE`, `SUSPENDED`, or `RENEWED`, and whose term *including the grace window* spans the as-of instant — `term_start` is on or before the as-of instant, and the as-of instant is on or before `term_end` extended by `grace_days` days. The installs in scope under the audit variant are those whose `status` is `ACTIVE` *or* `PENDING`, because in-flight installs are reserved against the pool for audit purposes. The audit variant is thus deliberately stricter on the consumed side and broader on the entitled side, so the same underlying data can produce a different position under audit than under live.

Finalizing a draft reconciliation computes its figures and locks the verdict. The `total_entitled_units` is the sum of `entitled_units` over the in-scope entitlements; the `total_consumed_units` is the sum of `required_core_units` over the in-scope installs; and the `position_units` is the total entitled minus the total consumed. The `verdict` is `OVER_DEPLOYED` when the position is strictly less than zero, and `COMPLIANT` otherwise — a position of exactly zero is compliant, not over-deployed. When the verdict is `OVER_DEPLOYED`, the finalize step mints a `ComplianceFinding` linked to the run through `true_up_reconciliation_id` and to the product through `software_product_id`, with a system-assigned `finding_type` (such as `OVER_DEPLOYED`, `EXPIRED_IN_GRACE`, or `NEGATIVE_AVAILABLE`), a human-readable `detail` captured at finalize time, and a `shortfall_units` equal to the magnitude of the negative position (the number of units over-deployed, never negative). As a cascade to the product, the product's `compliance_status` is set to `OVER_DEPLOYED` when the verdict is over-deployed and to `COMPLIANT` otherwise. The reconciliation itself moves from `DRAFT` to `FINALIZED`; a finalize attempted on an already-finalized run is rejected with `ERR_INVALID_STATE`. Reconciliations can be listed and filtered by `software_product_id` or `status`. The findings a run produced can be listed for that run, and findings overall can be listed and filtered by `software_product_id` or `true_up_reconciliation_id`.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource return `201 Created`. Operations that modify an existing resource — including every state transition, activation, return, approval, completion, reversal, and finalization — return `200 OK`. All list and single-resource reads return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/assets/_clock/set_current_utc` | Set the server wall clock | AssetManager, ComplianceOfficer |
| POST | `/assets/vendors` | Create a vendor | AssetManager |
| GET | `/assets/vendors/{id}` | Get a vendor | AssetManager, ComplianceOfficer |
| POST | `/assets/employees` | Create an employee | AssetManager |
| GET | `/assets/employees/{id}` | Get an employee | AssetManager, ComplianceOfficer, Employee |
| POST | `/assets/employees/{id}/transition` | Change an employee's status | AssetManager |
| POST | `/assets/software-products` | Create a software product | AssetManager |
| GET | `/assets/software-products/{id}` | Get a software product | AssetManager, ComplianceOfficer |
| GET | `/assets/software-products` | List software products | AssetManager, ComplianceOfficer |
| POST | `/assets/entitlements` | Create a license entitlement | AssetManager |
| GET | `/assets/entitlements/{id}` | Get a license entitlement | AssetManager, ComplianceOfficer |
| GET | `/assets/entitlements` | List entitlements | AssetManager, ComplianceOfficer |
| POST | `/assets/entitlements/{id}/activate` | Activate a draft entitlement | AssetManager |
| POST | `/assets/entitlements/{id}/transition` | Suspend, resume, or expire an entitlement | ComplianceOfficer |
| POST | `/assets/hardware` | Create a hardware asset | AssetManager |
| GET | `/assets/hardware/{id}` | Get a hardware asset | AssetManager, ComplianceOfficer, Employee |
| GET | `/assets/hardware` | List hardware assets | AssetManager, ComplianceOfficer |
| POST | `/assets/hardware/{id}/transition` | Move asset between IN_STOCK and IN_REPAIR | AssetManager |
| POST | `/assets/hardware/{id}/checkout` | Check out an asset to an employee | AssetManager |
| GET | `/assets/checkouts/{id}` | Get a checkout | AssetManager, ComplianceOfficer, Employee |
| GET | `/assets/checkouts` | List checkouts | AssetManager, ComplianceOfficer, Employee |
| POST | `/assets/checkouts/{id}/return` | Return an open checkout | AssetManager |
| POST | `/assets/checkouts/{id}/transition` | Mark a checkout lost | AssetManager |
| POST | `/assets/coverage` | Create a warranty/lease coverage record | AssetManager |
| GET | `/assets/coverage/{id}` | Get a coverage record | AssetManager, ComplianceOfficer |
| GET | `/assets/coverage` | List coverage records | AssetManager, ComplianceOfficer |
| POST | `/assets/coverage/{id}/transition` | Expire or cancel a coverage record | AssetManager |
| POST | `/assets/installations` | Create an installation record | AssetManager |
| GET | `/assets/installations/{id}` | Get an installation record | AssetManager, ComplianceOfficer |
| GET | `/assets/installations` | List installation records | AssetManager, ComplianceOfficer |
| POST | `/assets/installations/{id}/activate` | Activate a pending install | AssetManager |
| POST | `/assets/installations/{id}/transition` | Reject or uninstall an install | AssetManager |
| POST | `/assets/disposal-requests` | Submit a disposal request | AssetManager |
| GET | `/assets/disposal-requests/{id}` | Get a disposal request | AssetManager, ComplianceOfficer |
| GET | `/assets/disposal-requests` | List disposal requests | AssetManager, ComplianceOfficer |
| POST | `/assets/disposal-requests/{id}/approve` | Approve a submitted disposal | ComplianceOfficer |
| POST | `/assets/disposal-requests/{id}/reject` | Reject a submitted disposal | ComplianceOfficer |
| POST | `/assets/disposal-requests/{id}/complete` | Complete an approved disposal | ComplianceOfficer |
| POST | `/assets/disposal-requests/{id}/reverse` | Reverse a completed disposal | ComplianceOfficer |
| POST | `/assets/renewal-orders` | Create a renewal order | ComplianceOfficer |
| GET | `/assets/renewal-orders/{id}` | Get a renewal order | AssetManager, ComplianceOfficer |
| GET | `/assets/renewal-orders` | List renewal orders | AssetManager, ComplianceOfficer |
| POST | `/assets/renewal-orders/{id}/complete` | Complete a quoted renewal | ComplianceOfficer |
| POST | `/assets/renewal-orders/{id}/transition` | Cancel a quoted renewal | ComplianceOfficer |
| POST | `/assets/true-ups` | Create a true-up reconciliation | ComplianceOfficer |
| GET | `/assets/true-ups/{id}` | Get a true-up reconciliation | AssetManager, ComplianceOfficer |
| GET | `/assets/true-ups` | List true-up reconciliations | AssetManager, ComplianceOfficer |
| POST | `/assets/true-ups/{id}/finalize` | Finalize a draft true-up | ComplianceOfficer |
| GET | `/assets/true-ups/{id}/findings` | List findings produced by a true-up | AssetManager, ComplianceOfficer |
| GET | `/assets/findings/{id}` | Get a single compliance finding | AssetManager, ComplianceOfficer |
| GET | `/assets/findings` | List compliance findings | AssetManager, ComplianceOfficer |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 422 |
| `ERR_INVALID_TERM_WINDOW` | 422 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_ASSET_NOT_AVAILABLE` | 409 |
| `ERR_ASSET_NOT_RETIREABLE` | 409 |
| `ERR_ASSET_HAS_OPEN_CHECKOUT` | 409 |
| `ERR_EMPLOYEE_NOT_ACTIVE` | 409 |
| `ERR_ASSIGNMENT_LIMIT_REACHED` | 409 |
| `ERR_CHECKOUT_OVERLAP` | 409 |
| `ERR_COVERAGE_OVERLAP` | 409 |
| `ERR_COVERAGE_NOT_ENDED` | 409 |
| `ERR_TERM_NOT_ENDED` | 409 |
| `ERR_ENTITLEMENT_NOT_ACTIVE` | 409 |
| `ERR_ENTITLEMENT_EXCEEDED` | 409 |
| `ERR_RENEWAL_NOT_ELIGIBLE` | 409 |
| `ERR_DUPLICATE_KEY` | 409 |
