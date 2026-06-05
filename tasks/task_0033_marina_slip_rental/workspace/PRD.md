# Marina Slip Rental API — Product Requirements Document

## 1. Introduction

Coastal marinas run a deceptively complex business: every wet slip is a constrained physical resource with a length, a beam, a shore-power pedestal, and a calendar of overlapping reservations, while the tenants who rent those slips arrive with vessels of varying sizes, insurance policies that may have expired in the off-season, and — increasingly — a wish to live aboard their boat for months at a time. Pricing flexes with the season; pump-out services are subsidised at slips with integrated plumbing and billed at portable-cart rates everywhere else; tow-assistance coverage depends on whether the disabled vessel's insurance is current and whether the incident lies within the marina's contracted radius. Layered on top of all of this, harbor masters must hold tenant population within a regulated liveaboard cap, sweep stale transfer requests, and serialise check-outs so that a freed slip is offered to the next tenant in line rather than disappearing back into the open inventory.

This document specifies the Marina Slip Rental API, a single REST service that mediates between harbor masters, day-to-day marina staff, and individual tenants. It defines every entity the system tracks, the lifecycles those entities pass through, the calculations that pin nightly rates and surcharges, the validation rules that protect against over-booking and insurance lapses, and the cascading side effects that connect a single check-out to a waitlist promotion three hops away. Together these specifications describe a system whose correctness depends on temporal precision (half-open date intervals, server clock instants), quota arithmetic (liveaboard counts, slip availability windows), and a strictly ordered evaluation of safety checks (insurance before radius, role before existence, state before stale-version).

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request to the API must carry two headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, identifying which class of operator is acting. Requests that omit either header — or supply either as an empty string — are rejected with `ERR_UNAUTHENTICATED` and HTTP 401. Authenticated requests whose role lacks authority for the targeted endpoint are rejected with `ERR_FORBIDDEN` and HTTP 403.

The system recognises three roles with exact spelling `HarborMaster`, `MarinaStaff`, and `Tenant`. `HarborMaster` is the senior operator class with full authority across marina creation, slip provisioning, decommissioning, tenant registration, liveaboard approval and revocation, waitlist sweeps, and clock control; its powers are a superset of `MarinaStaff`. `MarinaStaff` handles day-to-day floor operations — check-in, check-out, pump-out completion, vessel registration, and tow-assist dispatch. `Tenant` is the end-user role corresponding to a boat owner who acts only on their own resources.

When `X-User-Role` is `Tenant`, `X-User-ID` is the `id` of the acting `Tenant`; ownership checks on any resource that references a `Tenant` compare the resource's `tenant_id` (or analogous foreign-key field, such as a lease's `tenant_id`) to `X-User-ID`. When `X-User-Role` is `HarborMaster` or `MarinaStaff`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it for audit purposes but does not compare it to any entity's `id`.

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

List endpoints accept two query parameters: `limit` and `offset`. The `limit` parameter defaults to 10, has a minimum of 1, and a maximum of 100; `offset` defaults to 0 with no upper bound beyond what the underlying data supports. List results are sorted by `created_at` ascending unless an endpoint description states otherwise. The `meta` block of every list response carries `limit`, `offset`, `total_count` (the total matching rows across the entire result set), and `has_more` (true when additional pages remain after the current `offset` + `limit` window).

### 2.4. Common Resource Properties and Versioning

Every persisted entity exposes an `id` field that is a server-minted UUID with no type prefix, and a `created_at` field stamped in ISO 8601 UTC with three fractional digits at the moment the row was first written. Entities that can be mutated after creation additionally expose `updated_at`, an ISO 8601 UTC timestamp refreshed on every mutation, and `version`, a monotonically increasing integer that begins at 1 on creation and increments by exactly 1 on each mutation that touches the row. The entities `Marina`, `Slip`, `Vessel`, `Tenant`, `Lease`, `PumpOutRequest`, and `TransferWaitlistEntry` carry the full set: `id`, `created_at`, `updated_at`, and `version`. The `TowAssistEvent` entity is append-only and immutable once dispatched; it carries `id` and `created_at` but neither `updated_at` nor `version`.

### 2.5. Nested Path Resolution and Existence Checks

Many endpoints embed identifiers in the URL path (a marina's id, a slip's id, a lease's id). The server resolves these path segments left to right and verifies that each referenced row exists before any downstream check runs. The first identifier in the path that does not resolve to a stored row yields `ERR_NOT_FOUND` with HTTP 404, regardless of what would have failed further along. Identifiers carried in the request body are validated after path identifiers — `marina_id`, `slip_id`, `lease_id`, `tenant_id`, `vessel_id`, `from_lease_id`, `target_slip_id`, and any other foreign-key reference must resolve to a stored row; if any does not, the response is `ERR_NOT_FOUND` HTTP 404.

### 2.6. Optimistic Concurrency Control on Slip Reservation

The lease-creation flow protects against stale views of the slip by requiring an explicit version pin. A request that creates a lease must carry `expected_slip_version`, an integer field whose value is the `version` of the target `Slip` as the client last observed it. If the slip's current `version` has advanced past that value — because another tenant successfully reserved the same slip in the interim, or because the harbor master decommissioned and the row mutated — the create is rejected with `ERR_STALE_VERSION` and HTTP 412, preventing the writer from layering a new reservation on top of a slip whose state has moved beyond their view. No other endpoint in this API requires a parent-version pin; the version-mismatch contract is exclusive to lease creation.

### 2.7. Validation Ordering

When multiple validations could apply to one request, the server evaluates them in a fixed priority order so that the rejection a caller sees is deterministic. Authentication is checked first: missing headers raise `ERR_UNAUTHENTICATED` before anything else looks at the request. Authorisation comes next, raising `ERR_FORBIDDEN` when the caller's role lacks authority. Then existence is verified — every path and body identifier must resolve, or `ERR_NOT_FOUND` is returned. Only after authentication, authorisation, and existence have all passed does the server consult state — a transition that is impossible from the entity's current state yields `ERR_INVALID_STATE`. The OCC stale-version check for lease creation runs after state, yielding `ERR_STALE_VERSION` only once the caller has authenticated, authorised, resolved every referenced row, and passed the basic state gate. Business-safety validations — insurance gating, liveaboard policy enforcement, slip size matching — run after the state and OCC layers, in the order presented in §3. Date-range and quota validations follow business-safety. Referential business checks (`ERR_VESSEL_TENANT_MISMATCH`, `ERR_WAITLIST_INELIGIBLE`) run last among business validations. Schema-level violations of the request body — missing required fields, wrong types, invalid enum values — surface as `ERR_INVALID_REQUEST` with HTTP 400 only when no higher-priority rejection applies.

### 2.8. Calculation Precision and Rounding

All monetary quantities in the system are integer cents — `base_daily_rate_cents`, `nightly_rate_cents`, `total_cost_cents`, and `charge_cents` all denominate in cents and never carry fractional value. Where a calculation multiplies cents by a ratio (for example, applying a seasonal multiplier), the result is rounded half up to the nearest cent at each rounding step. The seasonal pricing formula applies rounding twice — once after the seasonal multiplier and again after the liveaboard surcharge — so that the per-step rounded result is not arithmetically identical to a single end-of-formula rounding; this distinction is binding and is specified in detail in §3.

### 2.9. Hierarchical State Cascades and Version Bumps

Operations in this system frequently produce effects on more than one entity. When a slip transitions, its `version` is incremented and its `updated_at` is refreshed. When that transition cascades into a lease transition (for example, when checking in a vessel advances both the slip and the lease in one operation), the lease's `version` is also incremented and its `updated_at` refreshed. When a tenant's liveaboard status is revoked, the marina's tally moves and the marina's own `version` advances, and any reserved liveaboard lease for that tenant is cancelled — three rows mutate from one action. The hierarchical principle: every entity whose persisted state changes during a request has its `version` bumped by exactly 1 and its `updated_at` re-stamped to the same UTC instant. Cascades that touch three rows produce three independent version bumps.

### 2.10. Server Clock and Test-Driving

Insurance validity, waitlist expiry, and check-in date eligibility all reference the server's current UTC clock. To support deterministic testing, an admin-only test-driving capability allows the clock to be pinned to a supplied instant via a payload containing `to_iso8601`. After such a pin, all subsequent date-derived checks (insurance "strictly after current UTC date", "current clock date is on or after the lease's start date", waitlist age) read from that pinned instant rather than wall-clock time. The capability is reserved for harbor-master scope; it is not part of the public business surface and is included so that the temporal rules elsewhere in this document can be exercised reproducibly.

## 3. Business Logic & Workflows

### 3.1. Marina and Slip Provisioning

A marina is the top of the resource hierarchy. A `HarborMaster` creates one by supplying a `name`, a three-letter uppercase `harbor_code` that is unique across the system (for example `SFO`, `NYC`), and a `liveaboard_cap` — a non-negative integer expressing how many tenants may simultaneously hold approved liveaboard status while leasing a slip within this marina. The creator may also supply seasonal window bounds (`season_summer_start` and `season_summer_end`) in `MM-DD` form; when omitted, the marina defaults to summer running from `05-01` through `09-30` inclusive. `season_summer_end` must fall on a calendar date after `season_summer_start`. A `tow_assist_radius_nm` may be supplied to govern how far the marina's tow program reaches; if omitted, the default is 25.0 nautical miles. On creation the marina's `liveaboard_current_count` is initialised to zero and tracks the live count of tenants whose `liveaboard_status` is `APPROVED` and whose active lease's `marina_id` equals this marina; the field is recomputed on every tenant liveaboard transition and on every lease check-in or check-out.

Each marina hosts a collection of slips. Provisioning a slip requires the marina id in the URL path and a payload supplying `slip_number` (the human label, unique within the parent marina), `length_ft` and `beam_ft` (each strictly greater than zero, expressing the usable length and beam of the slip in feet), `power_amp` (the shore-power rating at the pedestal, one of `NONE`, `A30`, `A50`, `A100`), and `base_daily_rate_cents`, the unmultiplied nightly rate in integer cents. The body may also supply `pumpout_available` (defaulting to false) indicating whether the slip pedestal has an integrated pump-out connection, and `liveaboard_allowed` (defaulting to false) indicating whether the slip is permitted to host liveaboard tenants. A new slip enters service in `AVAILABLE` state; its `marina_id` is inherited from the path. Only a `HarborMaster` may create or decommission slips.

A slip's lifecycle runs `AVAILABLE → RESERVED → OCCUPIED → AVAILABLE` for routine business, with a terminal `OUT_OF_SERVICE` branch reachable from `AVAILABLE` via decommissioning. Decommissioning is a harbor-master-only capability and requires that the slip currently be `AVAILABLE` and that no lease referencing it is in `RESERVED` or `ACTIVE`; either condition violated yields `ERR_INVALID_STATE` HTTP 409. A successful decommission sets the slip's `status` to `OUT_OF_SERVICE` and bumps its `version`.

### 3.2. Tenant Onboarding and Vessel Registration

A `HarborMaster` registers a tenant by supplying a globally unique `email` and a `full_name`. A new tenant's `liveaboard_status` defaults to `NONE` and their `liveaboard_approved_at` is null. Tenants may register their own vessels (a `MarinaStaff` operator or a `HarborMaster` can do so on their behalf). Vessel registration requires a `tenant_id` identifying the owner, a `name` for display, the vessel's `loa_ft` and `beam_ft` (each strictly greater than zero, in feet), an `insurance_policy_number`, an `insurance_expires_on` date in `YYYY-MM-DD` form, and an `insurance_coverage_cents` figure in integer cents representing the hull insurance limit. Insurance is considered VALID at any clock instant strictly less than `YYYY-MM-DDT00:00:00Z` of `insurance_expires_on` — in other words, the prior day is covered, but at the start of the expiry date itself the policy is no longer valid.

### 3.3. Liveaboard Policy Lifecycle

The liveaboard policy is a per-tenant posture independent of any single lease, governed by the `Tenant.liveaboard_status` machine whose values are `NONE`, `PENDING`, `APPROVED`, and `REVOKED`. A tenant whose status is `NONE` or `REVOKED` may submit a liveaboard application; the application names the `marina_id` for which approval is sought. From `NONE` this transitions the tenant's `liveaboard_status` to `PENDING`; from `REVOKED` the same operation re-enters the review queue, also producing `PENDING`. This re-application loop makes the tenant's liveaboard machine cyclic: a previously revoked tenant can return to the queue and be approved again. Either branch bumps `version`.

From `PENDING`, two outcomes are reachable. A harbor master may approve, transitioning the tenant to `APPROVED`, stamping `liveaboard_approved_at` to the current UTC instant, incrementing the named marina's `liveaboard_current_count` by 1, and bumping both the tenant's and the marina's `version`. Approval is gated by the liveaboard quota: if the marina's current count is greater than or equal to its cap, approval is rejected with `ERR_LIVEABOARD_QUOTA_EXCEEDED` and HTTP 409. Alternatively, the harbor master may deny the application, returning the tenant to `NONE` and bumping their `version`.

Revocation runs from `APPROVED` to `REVOKED`. The harbor master supplies the `marina_id` whose count was previously incremented; the system decrements that marina's `liveaboard_current_count` by 1, advances the marina's `version`, and cascades a second mutation: every lease belonging to this tenant whose `is_liveaboard` is true and whose current `status` is `RESERVED` transitions to `CANCELLED`, with each cancelled lease incurring its own `version` bump. The revoked tenant's `version` is bumped as well. A revoked tenant may later re-enter the review loop via re-application as described above.

### 3.4. Reserving a Slip — Lease Creation and the OCC Pin

A `Tenant` reserves a slip by creating a lease. The request supplies `marina_id`, `slip_id`, `tenant_id` (which must match the acting tenant), `vessel_id` (identifying the vessel that will occupy the slip), `start_date` and `end_date` (each `YYYY-MM-DD`, with `end_date` strictly after `start_date`; an equal start and end yields `ERR_INVALID_DATE_RANGE` HTTP 422), an optional `is_liveaboard` flag (defaulting to false), and `expected_slip_version`, the integer version of the target slip as the client most recently observed it.

The system enforces these checks in the order described in §2.7. Once authentication, authorisation, and existence have passed, the slip must be in `AVAILABLE` state — any other state yields `ERR_INVALID_STATE` HTTP 409. Then the version pin is validated: the slip's current `version` must equal the supplied `expected_slip_version`, and a mismatch is rejected with `ERR_STALE_VERSION` HTTP 412. After the OCC pin, business-safety checks run. If `is_liveaboard` is true, then the slip's `liveaboard_allowed` must be true AND the tenant's `liveaboard_status` must be `APPROVED`; failure of either yields `ERR_LIVEABOARD_NOT_ALLOWED` HTTP 422. The slip must be large enough for the vessel: `loa_ft` of the vessel must be less than or equal to `length_ft` of the slip AND `beam_ft` of the vessel must be less than or equal to `beam_ft` of the slip; either bound violated yields `ERR_SLIP_SIZE_MISMATCH` HTTP 422.

After size matching, temporal overlap is checked. The system treats the lease window as the half-open interval starting on `start_date` (inclusive) and ending on `end_date` (exclusive). Two leases on the same slip collide when their half-open intervals intersect; day-exact adjacency, where one lease's `end_date` equals the next lease's `start_date`, does not collide because `end_date` is exclusive. A collision with any existing `RESERVED` or `ACTIVE` lease yields `ERR_SLIP_DATE_CONFLICT` HTTP 409. Finally, the lease's `vessel_id` must reference a vessel whose `tenant_id` equals the lease's `tenant_id`; a mismatch yields `ERR_VESSEL_TENANT_MISMATCH` HTTP 422.

A successful create produces a lease in `RESERVED` state with `nightly_rate_cents` and `total_cost_cents` both defaulting to 0 (they are pinned only at check-in), advances the slip from `AVAILABLE` to `RESERVED`, increments the slip's `version` by 1, and refreshes the slip's `updated_at`. The advance of the slip's `version` on a successful reservation is precisely why the OCC pin matters: a subsequent attempt by another tenant who observed the slip before this advance will fail the version check.

### 3.5. Check-In, Seasonal Pricing, and the Two-Step Multiplier

When the tenant arrives, a `MarinaStaff` (or `HarborMaster`) operator checks the lease in. Check-in is permitted only when the slip is currently `RESERVED` and the lease is currently `RESERVED`, and only when the current clock date is on or after the lease's `start_date`. Insurance must be VALID at check-in: the vessel's `insurance_expires_on` must lie strictly after the current UTC date AND its `insurance_coverage_cents` must be at least `MIN_INSURANCE_COVERAGE_CENTS` of fifty thousand dollars expressed in cents; if either fails, the operation is rejected with `ERR_INSURANCE_INVALID` HTTP 422. Size matching is re-evaluated at check-in (the vessel's `loa_ft` must be at most the slip's `length_ft` AND its `beam_ft` at most the slip's `beam_ft`; otherwise `ERR_SLIP_SIZE_MISMATCH` HTTP 422). If the lease's `is_liveaboard` is true, the slip's `liveaboard_allowed` must remain true AND the tenant's `liveaboard_status` must still be `APPROVED`, or `ERR_LIVEABOARD_NOT_ALLOWED` HTTP 422 is returned.

Upon passing every gate, the lease's `nightly_rate_cents` is pinned by the seasonal pricing rule, and the lease transitions from `RESERVED` to `ACTIVE` while the slip transitions from `RESERVED` to `OCCUPIED`, both with `version` and `updated_at` advances. The seasonal pricing rule applies a sequence of multiplications to the slip's `base_daily_rate_cents`, with rounding inserted between steps.

Step one selects the seasonal tier from the marina calendar. The lease falls into the SUMMER tier when its `start_date` (month-day component) lies on or between `season_summer_start` and `season_summer_end` inclusive, and into the WINTER tier otherwise. The SUMMER multiplier is one hundred fifty hundredths (numerator 150, denominator 100, i.e. one point five). The WINTER multiplier is eighty hundredths (numerator 80, denominator 100, i.e. zero point eight).

Step two computes an interim nightly rate by multiplying the slip's `base_daily_rate_cents` by the selected seasonal multiplier (numerator first, then dividing by denominator) and rounding the result half up to the nearest integer cent. The product is held as an integer in cents after this rounding.

Step three applies the liveaboard surcharge. When the lease's `is_liveaboard` is true, the interim nightly rate from step two is multiplied by one hundred ten hundredths (numerator 110, denominator 100, i.e. one point one), and the product is again rounded half up to the nearest integer cent; the result becomes the lease's `nightly_rate_cents`. When `is_liveaboard` is false, the surcharge multiplier is one hundred hundredths (numerator 100, denominator 100, i.e. one point zero) — a no-op — so the lease's `nightly_rate_cents` equals the result of step two. Rounding is applied independently at step two and at step three; the system does not collapse the two multiplications into a single multiplication and round only once, and the intermediate rounding at step two can produce a per-step rounded result that differs from sum-then-round arithmetic on certain inputs. The pinned `nightly_rate_cents` is never updated after this initial pinning.

Immediately after `nightly_rate_cents` is pinned, the lease's `total_cost_cents` is pinned by an aggregation rule. The number of nights is computed as `end_date` minus `start_date` in days using the half-open interval (so a lease from the 1st to the 4th is three nights). The base cost is the number of nights multiplied by the pinned `nightly_rate_cents`. When the lease's `is_liveaboard` is true, a utility surcharge equal to `LIVEABOARD_UTILITY_FEE_PER_NIGHT_CENTS` of fifteen dollars in cents multiplied by the number of nights is added on top; otherwise the surcharge is zero. The sum becomes the lease's `total_cost_cents` and is pinned at check-in and never updated thereafter.

### 3.6. Pump-Out Service

While a lease is `ACTIVE`, the tenant may request pump-out service. The request payload identifies the `lease_id`; the request is created in `PENDING` state with `requested_at` stamped to the server clock at creation. A pump-out request's `completed_at` and `charge_cents` are null and zero respectively until completion.

A `MarinaStaff` (or `HarborMaster`) operator marks the request `COMPLETED`. Completion requires the request to be in `PENDING` and the parent lease to be in `ACTIVE`; either violated yields `ERR_INVALID_STATE` HTTP 409. On completion, the request's `charge_cents` is pinned by the pump-out charge rule: if the slip's `pumpout_available` is true, the charge is zero (a marina with integrated plumbing absorbs the fee); otherwise the charge is `PUMPOUT_PORTABLE_FEE_CENTS` of twenty-five dollars in cents, reflecting the portable-cart operation. The request's `completed_at` is stamped to the current UTC instant and its `version` is bumped. A tenant may instead cancel a `PENDING` pump-out request, transitioning it from `PENDING` to `CANCELLED` and bumping its `version`; cancellation is rejected with `ERR_INVALID_STATE` HTTP 409 if the request is not in `PENDING`.

### 3.7. Tow Assistance — The Strict Step Ordering

A tow-assist dispatch is a synchronous evaluation rather than a multi-step workflow: the operator supplies `tenant_id`, `vessel_id`, `marina_id`, and `incident_distance_nm` (the nautical-mile distance from the marina to the incident, at least zero), and the system computes the dispatch outcome and persists a `TowAssistEvent` recording the result with `outcome` set to one of `COVERED`, `OUT_OF_RADIUS`, or `INSURANCE_INVALID` and `dispatched_at` stamped to the current UTC.

The outcome resolves through a fixed two-step evaluation in which the first failing step determines the result. Step one validates insurance: the vessel's `insurance_expires_on` must lie strictly after the current UTC date AND its `insurance_coverage_cents` must be at least `MIN_INSURANCE_COVERAGE_CENTS` (fifty thousand dollars in cents). Step two validates the radius: `incident_distance_nm` must be less than or equal to the marina's `tow_assist_radius_nm`. The outcome is `INSURANCE_INVALID` if step one fails; `OUT_OF_RADIUS` if step one passes but step two fails; and `COVERED` if both pass. Order is binding: when a single event fails both gates (expired insurance AND distance outside radius), the recorded outcome is `INSURANCE_INVALID` because the insurance step short-circuits before the radius step is reached.

### 3.8. Check-Out and the Three-Hop Cascade

A check-out by a `MarinaStaff` (or `HarborMaster`) operator transitions the lease from `ACTIVE` to `ENDED` and the slip from `OCCUPIED` to either `AVAILABLE` or back to `RESERVED`, depending on what the transfer waitlist holds for this slip. Check-out is permitted only when the slip is `OCCUPIED` and the lease is `ACTIVE`.

The cascade runs in three hops from a single operation. First, the lease transitions to `ENDED` and its `version` is bumped. Second, if the lease's `is_liveaboard` is true, the marina's `liveaboard_current_count` is decremented by 1 and the marina's `version` is bumped. Third, the system consults the transfer waitlist for the freed slip: candidates are all `TransferWaitlistEntry` rows whose `marina_id` equals the slip's `marina_id`, whose `target_slip_id` equals the freed slip's `id`, and whose `status` is `QUEUED`. The candidates are ordered by `requested_at` ascending, with ties broken by `created_at` ascending. If the candidate set is empty, the slip transitions plainly to `AVAILABLE` and its `version` is bumped — no further mutation. If the candidate set is non-empty, the head entry — the row with the earliest `requested_at` (and earliest `created_at` on ties) — transitions from `QUEUED` to `PROMOTED`, the slip transitions to `RESERVED` (re-using the same `AVAILABLE → RESERVED` move that a fresh reservation would make), the promoted entry's `version` is bumped, and the slip's `version` is bumped. The remaining `QUEUED` entries in the same `(marina_id, target_slip_id)` queue have their `position` field recomputed to reflect that the head has been removed.

A reserved lease that has not yet been checked in may instead be cancelled by the owning tenant, transitioning the lease from `RESERVED` to `CANCELLED` and the slip from `RESERVED` back to `AVAILABLE`. Both `version` counters advance. Cancellation requires the lease to be in `RESERVED` and the slip in `RESERVED`; either violated yields `ERR_INVALID_STATE` HTTP 409.

### 3.9. Transfer Waitlist Lifecycle

A tenant who currently holds an `ACTIVE` lease at a marina may register their intent to move to a different slip in the same marina by creating a `TransferWaitlistEntry`. The payload carries `marina_id`, `tenant_id` (the requesting tenant), `from_lease_id` (the tenant's current `ACTIVE` lease being transferred out of), and `target_slip_id` (the slip the tenant wishes to move into). The system enforces three referential conditions: the tenant must currently hold an `ACTIVE` lease at the named marina, the supplied `from_lease_id` must be that lease, and the `target_slip_id` must be a slip in the same marina; any failure yields `ERR_WAITLIST_INELIGIBLE` HTTP 422. On creation, `requested_at` is stamped to the server clock and `position` is computed as the 1-based index within the `(marina_id, target_slip_id)` queue ordered by `requested_at` ascending and `created_at` ascending; the entry enters in `QUEUED` state.

A queued entry can leave in three ways. The system itself promotes the head entry to `PROMOTED` when the targeted slip becomes available via the check-out cascade described above — the entry's `status` advances, the slip transitions to `RESERVED`, and subsequent positions are recomputed. The tenant may instead cancel their own queued entry, transitioning it from `QUEUED` to `CANCELLED` and recomputing positions for the remaining `QUEUED` entries in the same queue. A harbor master may run a sweep that expires every `QUEUED` entry whose age — the difference between the current UTC instant and the entry's `requested_at` — is greater than or equal to `WAITLIST_TTL_DAYS` days, advancing each matching entry to `EXPIRED` and recomputing positions for the remaining `QUEUED` entries. Every transition bumps the entry's `version`.

## 4. Endpoint Definitions

All endpoints return HTTP 200 on successful retrieval or modification of an existing resource. Endpoints that create a new persisted resource return HTTP 201. Error responses use the status codes catalogued in §5. The summary table below lists method, path, a brief description, and the roles authorised to call the endpoint; the full request body, response body, and side-effect semantics are described in §3.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /marinas | Create a marina. | HarborMaster |
| GET | /marinas | List marinas. | HarborMaster, MarinaStaff, Tenant |
| GET | /marinas/{id} | Retrieve one marina. | HarborMaster, MarinaStaff, Tenant |
| POST | /marinas/{id}/slips | Create a slip under a marina. | HarborMaster |
| GET | /slips | List slips, optionally filtered by marina or status. | HarborMaster, MarinaStaff, Tenant |
| GET | /slips/{id} | Retrieve one slip. | HarborMaster, MarinaStaff, Tenant |
| POST | /slips/{id}/decommission | Take a slip out of service. | HarborMaster |
| POST | /tenants | Register a tenant. | HarborMaster |
| GET | /tenants | List tenants. | HarborMaster, MarinaStaff |
| GET | /tenants/{id} | Retrieve one tenant. | HarborMaster, MarinaStaff, Tenant |
| POST | /tenants/{id}/liveaboard-applications | Apply (or re-apply) for liveaboard status. | Tenant |
| POST | /tenants/{id}/liveaboard-approve | Approve a pending liveaboard application. | HarborMaster |
| POST | /tenants/{id}/liveaboard-deny | Deny a pending liveaboard application. | HarborMaster |
| POST | /tenants/{id}/liveaboard-revoke | Revoke an approved liveaboard tenant. | HarborMaster |
| POST | /vessels | Create a vessel. | Tenant, MarinaStaff, HarborMaster |
| GET | /vessels | List vessels, optionally filtered by tenant. | HarborMaster, MarinaStaff, Tenant |
| GET | /vessels/{id} | Retrieve one vessel. | HarborMaster, MarinaStaff, Tenant |
| POST | /leases | Reserve a slip — create a lease in RESERVED. | Tenant |
| GET | /leases | List leases, optional filters. | HarborMaster, MarinaStaff, Tenant |
| GET | /leases/{id} | Retrieve one lease. | HarborMaster, MarinaStaff, Tenant |
| POST | /leases/{id}/check-in | Check vessel into reserved slip — Lease RESERVED → ACTIVE. | MarinaStaff, HarborMaster |
| POST | /leases/{id}/check-out | Check vessel out — Lease ACTIVE → ENDED. | MarinaStaff, HarborMaster |
| POST | /leases/{id}/cancel | Tenant cancels a reserved lease. | Tenant |
| POST | /pump-out-requests | Tenant requests pump-out service against an ACTIVE lease. | Tenant |
| GET | /pump-out-requests | List pump-out requests, optionally filtered. | HarborMaster, MarinaStaff, Tenant |
| GET | /pump-out-requests/{id} | Retrieve one pump-out request. | HarborMaster, MarinaStaff, Tenant |
| POST | /pump-out-requests/{id}/complete | Mark a pump-out request COMPLETED. | MarinaStaff, HarborMaster |
| POST | /pump-out-requests/{id}/cancel | Cancel a pending pump-out request. | Tenant |
| POST | /tow-assist-events | Dispatch tow assistance — synchronous evaluation. | Tenant, MarinaStaff, HarborMaster |
| GET | /tow-assist-events | List tow-assist events, optionally filtered. | HarborMaster, MarinaStaff, Tenant |
| GET | /tow-assist-events/{id} | Retrieve one tow-assist event. | HarborMaster, MarinaStaff, Tenant |
| POST | /transfer-waitlist | Request transfer to a different slip in the same marina. | Tenant |
| GET | /transfer-waitlist | List transfer-waitlist entries, optionally filtered. | HarborMaster, MarinaStaff, Tenant |
| GET | /transfer-waitlist/{id} | Retrieve one transfer-waitlist entry. | HarborMaster, MarinaStaff, Tenant |
| POST | /transfer-waitlist/{id}/cancel | Cancel a queued transfer-waitlist entry. | Tenant |
| POST | /transfer-waitlist/expire-stale | Sweep QUEUED waitlist entries older than the TTL. | HarborMaster |
| POST | /_clock/set_current_utc | Test-driving: pin the server's current UTC clock. | HarborMaster |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|---|---|
| ERR_UNAUTHENTICATED | 401 |
| ERR_FORBIDDEN | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_INVALID_STATE | 409 |
| ERR_STALE_VERSION | 412 |
| ERR_INSURANCE_INVALID | 422 |
| ERR_LIVEABOARD_NOT_ALLOWED | 422 |
| ERR_SLIP_SIZE_MISMATCH | 422 |
| ERR_SLIP_DATE_CONFLICT | 409 |
| ERR_INVALID_DATE_RANGE | 422 |
| ERR_LIVEABOARD_QUOTA_EXCEEDED | 409 |
| ERR_VESSEL_TENANT_MISMATCH | 422 |
| ERR_WAITLIST_INELIGIBLE | 422 |
| ERR_INVALID_REQUEST | 400 |
