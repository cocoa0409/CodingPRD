# Vessel Agency Port Calls API — Product Requirements Document

## 1. Introduction

A port agency firm lives in the seam between a ship and the shore. Every port call arrives with a stack of obligations that must be discharged on someone else's clock: pre-arrival filings to port state control, immigration, customs, and the harbor master; a berth window that competes with every other vessel in port; pilots, tugs, line boats, and launches drawn from a small pool of shared physical units; crew signing on and off with passports, visas, and shore passes that expire at inconvenient hours; provisions, bunkers, stores, and repairs delivered by vendors who invoice what they like; and, hanging over all of it, the disbursement account — the pro-forma estimate the agency sends to the shipowner before arrival, funded by cash advances, and the final account rendered after sailing, where estimates meet actuals and every discrepancy becomes a negotiation.

This document specifies the Vessel Agency Port Calls API, the system of record for that entire workflow. The **Port Call** is the organizing entity, and the **Disbursement Account** is its financial spine: estimates are computed from published port tariffs and mirrored from operational orders, funding advances are tracked against a mandatory pre-funding threshold, and finalization, dispute, and settlement follow a strict segregation-of-duties discipline. The API enforces posture-driven gating — a vessel cannot sail while crew movements are open, cargo documents are held, a critical husbandry case is unresolved, or the account is underfunded — and it models time through a controllable logical clock so that deadlines, window openings, late-cancellation cutoffs, and shore-pass expiry are deterministic. Role-based access control, optimistic concurrency on the port call, and a dual-variant principal credit exposure calculation complete the system-wide contract defined in Section 2; Section 3 walks the business workflows; Sections 4 and 5 give the endpoint and error catalogues.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through a set of mandatory HTTP headers. Each request must include `X-User-ID` to identify the acting user and `X-User-Role` to specify their operational capacity. The system recognizes eight roles with these exact spellings: `AgencyAdmin`, `AgencyOps`, `AgencyFinance`, `PortAuthority`, `PrincipalRep`, `VendorRep`, `CrewingAgent`, and `HusbandryOfficer`. A request that arrives without these headers, or whose `X-User-Role` is not one of the declared roles, is rejected with `ERR_UNAUTHENTICATED`. A request whose role is not listed among the roles authorized for the target endpoint is rejected with `ERR_FORBIDDEN_ROLE`.

The meaning of `X-User-ID` depends on the role. When `X-User-Role` is `PrincipalRep`, `X-User-ID` is the `id` of the acting **Principal**; ownership checks on any resource that references a Principal compare the resource's `principal_id` to `X-User-ID`, and a mismatch is rejected with `ERR_NOT_RESOURCE_OWNER`. When `X-User-Role` is `VendorRep`, `X-User-ID` is the `id` of the acting **Vendor**; ownership checks on any resource that references a Vendor compare the resource's `vendor_id` to `X-User-ID`, and a mismatch is likewise rejected with `ERR_NOT_RESOURCE_OWNER`. For the remaining six roles — `AgencyAdmin`, `AgencyOps`, `AgencyFinance`, `PortAuthority`, `CrewingAgent`, and `HusbandryOfficer` — `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it (for example, as `created_by_user_id` or `finalized_by_user_id` on a Disbursement Account, where segregation of duties requires it) but does not compare it to any entity's `id`.

`AgencyAdmin` is the agency superuser with hierarchical override: it alone administers principals and vendors, resolves escalated disputes, grants husbandry departure waivers, drives the logical clock, and shares the port-call cancellation capability with `AgencyOps`. The other roles own their operational lanes as enumerated in Section 4; every role may use all read endpoints.

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
- Pagination-related fields in `meta` (`limit`, `offset`, `total_count`, `has_more`) are included only for list endpoints; the `meta` of any other success response carries just `api_request_id` and `api_request_timestamp`.
- Datetime values supplied by clients (for example `eta`, `window_start`, and `shore_pass_expires_at`) are echoed back in ISO 8601 UTC with fractional seconds only when the value carries sub-second precision, whereas the system-managed `created_at` and `updated_at` always carry exactly three fractional digits.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return. If not provided, it defaults to 10, with a minimum of 1 and a maximum of 100; out-of-range and unparsable values are never rejected — `limit` is clamped into the [1, 100] range and an unparsable `limit` falls back to the default. The `offset` parameter specifies the number of items to skip and defaults to 0; a negative `offset` is floored to 0 and an unparsable `offset` falls back to the default.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order, with ties broken by creation (insertion) order — a tie-break that matters because the logical clock may stand still across several creations. One refinement applies inside a disbursement account: an account's lines are presented in `created_at` ascending order with ties broken by `category` in ascending alphabetical order and then by insertion order, as detailed in §3.8.

Paginated list responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and Atomic Writes

Every resource in this API carries a standard set of system-managed fields:

- **`id` (string):** A unique, server-minted identifier for the resource, formatted as a UUID with no type prefix.
- **`created_at` (string):** An ISO 8601 timestamp in UTC with three fractional digits, indicating when the resource was first created.
- **`updated_at` (string):** An ISO 8601 UTC timestamp with three fractional digits, refreshed upon any change to the resource's properties, including changes driven by cascades and recomputation.
- **`version` (integer):** A system-managed integer that starts at 1 on creation and increments with every modification to the resource. This field backs the optimistic concurrency control described in §2.8.

All mutations are atomic within their request: when an operation cascades across berth windows, notifications, crew movements, orders, account lines, and totals — as port-call cancellation and sailing do — the entire graph of changes commits together or not at all, and every touched resource reflects the write in its `updated_at` and `version`.

### 2.5. The Logical Clock

The system never consults wall-clock time. Every notion of "now" — filing deadlines, window openings, late-cancellation cutoffs, shore-pass expiry, receipt timestamps — is read from a logical clock whose startup default, before anyone sets it, is exactly `2026-05-01T00:00:00Z`. An `AgencyAdmin`-only test-driving capability advances the logical clock to a supplied `to_iso8601` instant — a missing or unparsable `to_iso8601` is rejected with `ERR_INVALID_REQUEST` — and the capability's response reports the resulting `current_utc`. The lazy shore-pass expiry evaluation described in §3.6 runs against the new time on the next read after the clock moves.

### 2.6. Monetary Precision and Rounding

All monetary values in the system are carried as integer cents; there are no fractional-cent amounts anywhere in the API. Wherever a calculation produces a fractional cent — the per-line agency fee, the eighty-percent advance requirement, the late-cancellation fee, the port-dues line amount — the result is rounded to integer cents using the round-half-up method (ties round away from zero), applied exactly once at the point each rule specifies. Percentage quantities that are exposed to clients, notably a purchase order's `variance_pct`, are rounded half-up to two decimal places. Interval comparisons on datetimes are evaluated at second precision.

### 2.7. Request Validation Order

When several rules could reject the same request, the order in which checks run determines which error the client observes. The API evaluates every request through a fixed pipeline, earlier stages first:

1. **Authentication** — the `X-User-ID` and `X-User-Role` headers are present and the role is declared; otherwise `ERR_UNAUTHENTICATED` (HTTP 401).
2. **Role authorization** — the acting role appears in the endpoint's authorized set, including the conditional actor rules such as the kind-dependent service-order confirmation described in §3.5; otherwise `ERR_FORBIDDEN_ROLE` (HTTP 403).
3. **Path existence** — every identifier in the URL path is resolved left to right; the first identifier that does not resolve to an existing resource yields `ERR_NOT_FOUND` (HTTP 404).
4. **Payload reference existence** — every foreign-key-style field in the request body (`port_call_id`, `vendor_id`, `da_id`, `da_line_id`, `berth_window_id`, `crew_change_id`) resolves to an existing resource; otherwise `ERR_NOT_FOUND` (HTTP 404).
5. **Entity-backed ownership** — for `PrincipalRep` and `VendorRep`, the caller's `X-User-ID` must equal the owning `principal_id` or `vendor_id` of the resource being acted on; otherwise `ERR_NOT_RESOURCE_OWNER` (HTTP 403).
6. **State-machine legality** — the target resource's state machine must permit the requested transition from its current state, including the account-status preconditions on advance creation and dispute creation and the phase restriction on port-call patching; otherwise `ERR_INVALID_STATE` (HTTP 409).
7. **Safety gates** — the critical-husbandry gate at sailing; `ERR_OPEN_CRITICAL_HUSBANDRY` (HTTP 422).
8. **Temporal rules** — deadlines, window ordering, overlap checks, window-opening leads, passport validity, and shore-pass expiry, each with its own error from §5.
9. **Business constraints** — per-call uniqueness, notification coverage, berth and crew gates at movement operations, document release gates, the visa branch rules, port-call editability, sailing and closure preconditions, and segregation of duties.
10. **Referential business rules** — principal and vendor activity status, vendor category and kind matching, and the kind-matched confirmation actor (`ERR_CONFIRM_ROLE_MISMATCH`, HTTP 403).
11. **Fiscal gates** — funding sufficiency at sailing, the principal credit gate, and the settlement preconditions.
12. **Optimistic concurrency** — the `expected_port_call_version` comparison of §2.8; a mismatch yields `ERR_STALE_VERSION` (HTTP 412).
13. **Request shape** — required fields present, enum values valid, and numeric ranges respected (`vessel_gt` greater than zero, monetary amounts positive where required, `quantity` at least one); otherwise `ERR_INVALID_REQUEST` (HTTP 400). This check runs last, after all state and business rules, so a malformed body against a resource in an illegal state surfaces the state error, not the shape error.

### 2.8. Optimistic Concurrency Control

Two write endpoints carry an optimistic-concurrency obligation on the Port Call, and both name the same input field. A disbursement-account creation request must carry `expected_port_call_version` holding the caller's last observed `version` of the target port call; because creating an account legitimately supersedes any existing pro-forma account of the same call, a writer acting on a stale view would otherwise silently replace an account it never saw. A port-call schedule patch must likewise carry `expected_port_call_version`, because schedule edits legitimately overwrite the same ETA/ETD fields and the check forces the second writer to re-read. In both cases, if the supplied value does not match the port call's current `version`, the request is rejected with `ERR_STALE_VERSION` (HTTP 412). No other endpoint accepts a version field.

### 2.9. Shared Berth and Service-Unit Scheduling

Berths and service units are shared physical resources across all port calls, and the two kinds of resource use deliberately different overlap mathematics.

A **berth window** reserves a `berth_code` as a half-open interval: the window occupies from its `start_at` up to but not including its `end_at`. A candidate window conflicts with an existing window on the same `berth_code` in `CONFIRMED` or `OCCUPIED` status if and only if the existing window starts strictly before the candidate ends and the candidate starts strictly before the existing window ends. Mere adjacency — one window's `end_at` exactly equal to the other's `start_at` — is not a conflict. A conflicting confirmation is rejected with `ERR_BERTH_WINDOW_OVERLAP` (HTTP 409).

A **service order** reserves a `resource_unit` with a turnaround buffer: each requested window is inflated by forty-five minutes on both ends and compared as a closed interval. A candidate order conflicts with an existing order on the same `resource_unit` in `CONFIRMED` or `IN_PROGRESS` status if and only if the existing order's inflated start is at or before the candidate's inflated end and the candidate's inflated start is at or before the existing order's inflated end. Inflated intervals that merely touch do conflict, so two raw windows on the same unit are only safe when the gap between them is strictly greater than ninety minutes. A conflicting confirmation is rejected with `ERR_RESOURCE_UNIT_OVERLAP` (HTTP 409).

Uncommitted reservations never occupy: a berth window in `REQUESTED` and a service order in `ORDERED` block nothing — each is only checked against the committed schedule at the moment of its own confirmation.

### 2.10. Tariff Publication and Version Pinning

Port charges are priced from published **Tariff** records, each scoped to a `port_code` and a `component`. Publishing a new tariff supersedes every currently `PUBLISHED` tariff with the same `port_code` and `component`, moving them to `SUPERSEDED`. Supersession is not retroactive: disbursement-account lines that were estimated against an earlier publication keep their pinned `tariff_id` and their computed estimate, and only future estimates and final actualizations price against the newly published tariff. This pinning is what allows a pro-forma account and the final account of the same call to legitimately diverge when a tariff is republished mid-call.

### 2.11. Disbursement Ledger Invariants

The disbursement account is a live ledger whose derived totals are recomputed eagerly, never lazily. Every mutation that creates, updates, reverses, or actualizes an account line recomputes the account totals, and every funding-advance creation, application, or refund does the same. The evaluation order inside a recompute is pinned: line amounts first, then the per-line agency fee, then the advance requirement derived from the fee-inclusive total. The account's available funding — received minus applied minus refunded — is an invariant that never goes negative. A `SUPERSEDED` account keeps its stored totals frozen exactly as they were at supersession and is excluded from the principal exposure calculation of §3.1; at most one non-`SUPERSEDED` account exists per port call at any time.

## 3. Business Logic & Workflows

### 3.1. Principals, Credit Exposure, and Call Nomination

An `AgencyAdmin` registers a shipping company as a **Principal** with its legal `name`, an operations `contact_email`, and a `credit_limit_cents` ceiling expressed in cents — a ceiling of zero means the principal's credit is unlimited. New principals start `ACTIVE`; an admin may later suspend and reinstate them, flipping `status` between `ACTIVE` and `SUSPENDED`. A suspended principal cannot open new business: port-call creation for a principal that is not `ACTIVE` is rejected with `ERR_PRINCIPAL_SUSPENDED`.

An `AgencyOps` agent nominates a port call by supplying the owning `principal_id`, the `vessel_name`, the `imo_number` carried as a non-empty string (conventionally the seven-digit IMO number; no format check is enforced), the `vessel_gt` gross tonnage as a positive integer, the `flag_state` ISO code, the `port_code` UN/LOCODE, the estimated `eta` and `etd` timestamps in UTC with `etd` strictly later than `eta`, a free-text `cargo_description`, and optionally the `hazmat_flag`, which defaults to false when omitted. The new call starts in `ops_status` `NOMINATED`. At creation the system derives `alongside_days_estimated` — the hours between `eta` and `etd` divided by twenty-four, rounded up to a whole number of days, with a minimum of one day. The fields `actual_arrival_at` and `actual_sailed_at` remain null until the corresponding movement is recorded, and `alongside_days_actual` likewise remains null until the vessel sails, when it is computed from the two actual timestamps with the same round-up, minimum-one-day rule.

Before the nomination is accepted, the credit gate runs. The principal's forward-looking exposure must remain strictly below `credit_limit_cents` — a principal already at or beyond its ceiling is rejected with `ERR_CREDIT_LIMIT_EXCEEDED`, and an unlimited (zero) ceiling always passes. The exposure itself is computed in two variants, both restricted to the non-`SUPERSEDED` accounts of the principal's port calls whose `ops_status` is neither `CLOSED` nor `CANCELLED`. The **forward-looking** variant counts each account at `total_final_cents` when the account is `FINAL`, `DISPUTED`, or `SETTLED`, and at `total_estimated_cents` while it is still `PRO_FORMA`, `SENT_TO_PRINCIPAL`, or `FUNDED` — money not yet received still counts as exposure; the sum is reported as `forward_exposure_cents`. The **cash-basis** variant counts each account at `advances_applied_cents` alone while the account is pre-final, and at `advances_applied_cents` plus the positive part of `total_final_cents` minus `advances_applied_cents` (zero when the applied advances already cover the final total) once the account is `FINAL`, `DISPUTED`, or `SETTLED`; the sum is reported as `cash_basis_exposure_cents`. Consider an account estimated at 100000 cents with 20000 cents applied: it contributes 100000 to the forward figure but only 20000 to the cash-basis figure. A read-only capability reports both figures alongside `credit_limit_cents` and `credit_headroom_cents`, the latter being the ceiling minus the forward exposure, or null when the ceiling is unlimited. Principal listings may be filtered by `status`; port-call listings accept `principal_id`, `ops_status`, and `port_code` filters.

While the call remains in `NOMINATED` or `PRE_ARRIVAL_FILED`, an `AgencyOps` agent may patch its schedule and cargo fields — any of `eta`, `etd`, `cargo_description`, `hazmat_flag`, and `vessel_gt` — carrying `expected_port_call_version` per §2.8; once the call has moved past filing, the same edit fails with `ERR_INVALID_STATE`. A successful patch bumps the call's `version`, recomputes `alongside_days_estimated`, and re-derives the totals of the call's pro-forma account when one exists.

A general editability rule protects everything below the call: creating or acting on any child resource of a call whose `ops_status` is `CANCELLED` or `CLOSED` is rejected with `ERR_PORT_CALL_NOT_EDITABLE`, and individual operations may narrow the editable phase further, as their workflows note.

### 3.2. Authority Filings and the Path to Clearance

Before a vessel may enter, the agency files with four authorities. An `AgencyOps` agent creates each **Authority Notification** with the `port_call_id` it serves, an `authority_type` of `PORT_STATE_CONTROL`, `IMMIGRATION`, `CUSTOMS`, or `HARBOR_MASTER`, and a free-text `payload_summary` describing the filing package. Each authority type may exist at most once per port call among notifications that are not `WITHDRAWN`; a duplicate type is rejected with `ERR_DUPLICATE_NOTIFICATION_TYPE`. New notifications start in `DRAFT`.

Submission by an `AgencyOps` agent moves a notification from `DRAFT` to `SUBMITTED` and stamps `submitted_at` from the logical clock; submission is only possible while the parent call is still in `NOMINATED` or `PRE_ARRIVAL_FILED`, and later attempts fail with `ERR_PORT_CALL_NOT_EDITABLE`. The authority side then answers: a `PortAuthority` officer acknowledges a `SUBMITTED` filing, recording the supplied `authority_reference` on the notification, or rejects it, recording the supplied `reason` as the notification's `rejection_reason`. Rejection is not terminal for the filing cycle — an `AgencyOps` agent may resubmit a `REJECTED` notification, which returns it to `SUBMITTED`, increments `revision_count`, restamps `submitted_at`, and retains the prior `rejection_reason` for audit; resubmission honors the same editable-phase gate as the initial submission. `ACKNOWLEDGED` and `WITHDRAWN` are the terminal states, and withdrawal is the system's doing through the port-call cancellation cascade of §3.3, which carries `DRAFT`, `SUBMITTED`, and `REJECTED` notifications to `WITHDRAWN`. Notification listings accept `port_call_id`, `status`, and `authority_type` filters. Every state-machine rejection on this lifecycle surfaces as `ERR_INVALID_STATE`.

With the filings in flight, an `AgencyOps` agent files the pre-arrival package, transitioning the call from `NOMINATED` to `PRE_ARRIVAL_FILED`. Two gates guard this filing, and the deadline gate belongs to the temporal stage of §2.7: the logical clock must read no later than twenty-four hours before the call's `eta` — filing after that deadline fails with `ERR_PRE_ARRIVAL_DEADLINE_MISSED` — and at least one notification of each of the four authority types must exist for the call in `SUBMITTED` or `ACKNOWLEDGED` status, with any shortfall reported as `ERR_NOTIFICATIONS_OUTSTANDING`. A successful filing bumps the call's `version`.

Clearance itself belongs to the port: a `PortAuthority` officer grants clearance, transitioning the call from `PRE_ARRIVAL_FILED` to `CLEARED_TO_ENTER`. The gate is stricter than at filing time — every authority notification of the call must be `ACKNOWLEDGED`, with at least one per `authority_type` — and any notification still outstanding fails with `ERR_NOTIFICATIONS_OUTSTANDING`. Granting clearance bumps the call's `version`.

### 3.3. Berth Windows, Arrival, Sailing, and Call Cancellation

An `AgencyOps` agent requests a **Berth Window** with the `port_call_id` it serves, the shared `berth_code` (for example, a named berth such as BERTH-04), and the `start_at` and `end_at` bounds; the start must be strictly earlier than the end, and an inverted window is rejected with `ERR_WINDOW_INVALID`. New windows start `REQUESTED`. A `PortAuthority` officer confirms a `REQUESTED` window, provided the parent call is not `CANCELLED` or `CLOSED` (`ERR_PORT_CALL_NOT_EDITABLE`) and the half-open overlap check of §2.9 passes against every `CONFIRMED` or `OCCUPIED` window on the same `berth_code` (`ERR_BERTH_WINDOW_OVERLAP`). Window listings accept `port_call_id`, `berth_code`, and `status` filters.

Occupation and release track the physical reality. An `AgencyOps` agent marks a `CONFIRMED` window occupied once the logical clock has reached its `start_at` — an early attempt fails with `ERR_WINDOW_NOT_STARTED` — and only while the parent call's `HARBOR_MASTER` notification is `ACKNOWLEDGED`, failing otherwise with `ERR_HM_ACK_OUTSTANDING`; occupation stamps `occupied_at` from the clock. Releasing an `OCCUPIED` window stamps `released_at`, and release also happens automatically when the vessel sails, as described below. A window may be cancelled by an `AgencyOps` agent from `REQUESTED` or `CONFIRMED`; any other source state fails with `ERR_INVALID_STATE`. `RELEASED` and `CANCELLED` are terminal.

Recording arrival transitions the call from `CLEARED_TO_ENTER` to `ALONGSIDE`. The `AgencyOps` agent supplies a `berth_window_id`, which must reference a window belonging to this call — a window of another call fails with `ERR_BERTH_WINDOW_MISMATCH` — and that window must currently be `OCCUPIED`, failing otherwise with `ERR_BERTH_NOT_OCCUPIED`. The arrival stamps `actual_arrival_at` from the logical clock and bumps the call's `version`.

Recording sailing is the most heavily gated operation in the system; an `AgencyOps` agent moves the call from `ALONGSIDE` to `SAILED` only when every one of the following holds. The supplied `berth_window_id` must reference a window of this call (`ERR_BERTH_WINDOW_MISMATCH`) that is `OCCUPIED` (`ERR_BERTH_NOT_OCCUPIED`). No husbandry case of this call with `severity` `CRITICAL` may sit in `OPEN` or `IN_TREATMENT` without its `departure_waiver_granted` flag set (`ERR_OPEN_CRITICAL_HUSBANDRY`). No crew change of this call may remain in `REQUESTED`, `DOCS_VERIFIED`, `VISA_PENDING`, `VISA_GRANTED`, or `PASS_EXPIRED` — a movement in `SHORE_PASS_ISSUED` does not block departure (`ERR_OPEN_CREW_CHANGES`). No cargo document of this call may be `ON_HOLD` (`ERR_CARGO_DOCS_ON_HOLD`). And the money must be in order: a non-`SUPERSEDED` disbursement account must exist in one of `SENT_TO_PRINCIPAL`, `FUNDED`, `FINAL`, `DISPUTED`, or `SETTLED` — a call whose account is still `PRO_FORMA`, absent, or superseded fails with `ERR_DA_NOT_SENT` — and the account's net funding, meaning `advances_received_cents` minus `advances_refunded_cents`, must be at least `advance_required_cents`, with exact equality satisfying the gate (`ERR_FUNDING_SHORTFALL`).

A recorded sailing cascades through three links. First, the referenced berth window transitions to `RELEASED` with `released_at` stamped from the clock. Second, the account's `PORT_DUES` line actualizes through the final variant of the port-dues calculation of §3.8 — priced from the actual timestamps and from the tariff `PUBLISHED` at sailing time, falling back to the line's pinned tariff when no tariff is currently `PUBLISHED` for the port and component — and the line moves to `ACTUALIZED`. Third, the account's totals are recomputed; should the account still be `PRO_FORMA`, the actual is recorded on the line without advancing the account's status. The sailing stamps `actual_sailed_at`, computes `alongside_days_actual`, and bumps the call's `version`.

Closure belongs to finance: an `AgencyFinance` controller closes a `SAILED` call, transitioning it to `CLOSED`, only when the call's non-`SUPERSEDED` disbursement account has reached `SETTLED`; an unsettled account fails with `ERR_DA_NOT_SETTLED`. Closure bumps the call's `version`.

Cancellation unwinds everything. An `AgencyOps` agent or an `AgencyAdmin` may cancel a call from `NOMINATED`, `PRE_ARRIVAL_FILED`, `CLEARED_TO_ENTER`, or `ALONGSIDE`; from any other state the request fails with `ERR_INVALID_STATE`. The cancellation cascades through three links, all committed atomically per §2.4. Link one: every berth window of the call in `REQUESTED` or `CONFIRMED` moves to `CANCELLED`; every authority notification in `DRAFT`, `SUBMITTED`, or `REJECTED` moves to `WITHDRAWN`; every crew change in `REQUESTED`, `DOCS_VERIFIED`, `VISA_PENDING`, `VISA_GRANTED`, `SHORE_PASS_ISSUED`, or `PASS_EXPIRED` moves to `CANCELLED`; every purchase order in `DRAFT`, `SENT`, or `ACKNOWLEDGED` moves to `CANCELLED`; and every service order in `ORDERED` or `CONFIRMED` moves to `CANCELLED` with `cancellation_fee_cents` of zero — a port-call cancellation never incurs late fees. Link two: each service-order and purchase-order cancellation reverses its mirrored account line, driving the line's `estimated_cents` to zero while the line stays `ESTIMATED` and retains its `source_ref`. Link three: the account's totals are recomputed after all line reversals; an account in `PRO_FORMA`, `SENT_TO_PRINCIPAL`, or `FUNDED` remains open, and its funding gates re-derive from the new totals. The cancellation bumps the call's `version`.

### 3.4. Vendors and Purchase Orders

An `AgencyAdmin` registers each supplier as a **Vendor** with its legal `name`, a `categories` list that must be a non-empty subset of `PROVISIONS`, `BUNKERS`, `REPAIRS`, and `STORES`, and a `contact_email`. Vendors start `ACTIVE`. Suspending a vendor moves it to `SUSPENDED`; suspension never force-cancels purchase orders already in flight, but it blocks new purchase-order creation, sending, and acknowledgment, as well as confirmation of non-pilot service orders — each rejected with `ERR_VENDOR_SUSPENDED`. Reinstatement returns the vendor to `ACTIVE`. Vendor listings accept a `status` filter.

Provisioning begins when an `AgencyOps` agent creates a **Purchase Order** with the `port_call_id` it provisions, the supplier's `vendor_id`, a `category` drawn from the same four supply categories, a strictly positive `estimated_cents`, and the `needed_by` delivery instant in UTC. The chosen `category` must appear in the vendor's `categories`, failing which the creation is rejected with `ERR_VENDOR_CATEGORY_MISMATCH`, and the vendor must be `ACTIVE` (`ERR_VENDOR_SUSPENDED`). The order starts in `DRAFT`. Whenever the call has a disbursement account in `PRO_FORMA`, `SENT_TO_PRINCIPAL`, or `FUNDED`, creation also appends a mirror line to the account carrying the order's estimate — the line's `source_type` is `PURCHASE_ORDER`, its `category` matches the order's, and its `source_ref` records the origin in the form PurchaseOrder:<id> — the order's `da_line_id` is set to that mirror, and the account totals are recomputed. Order listings accept `port_call_id`, `vendor_id`, `da_line_id`, and `status` filters.

The order then walks a vendor-facing lifecycle. An `AgencyOps` agent sends a `DRAFT` order to the vendor (`SENT`), provided the vendor is still `ACTIVE`. The owning `VendorRep` acknowledges it (`SENT` → `ACKNOWLEDGED`), where ownership means the caller's `X-User-ID` equals the order's `vendor_id` — anyone else is rejected with `ERR_NOT_RESOURCE_OWNER` — and the vendor must still be `ACTIVE`. The same owning `VendorRep` marks delivery (`ACKNOWLEDGED` → `DELIVERED`).

Invoicing carries the divergence fork. The owning `VendorRep` submits `invoiced_cents` — a non-negative integer — against a `DELIVERED` order; the system stores `invoiced_cents`, recomputes `variance_pct`, and forks on its absolute value. The variance itself is the invoiced amount minus the estimate, divided by the estimate, expressed as a percentage and rounded half-up to two decimal places; when the estimate is zero, the variance is defined as 0.0 if the invoice is also zero and as the sentinel 999.99 otherwise, standing in for an infinite overage. An absolute variance of at most 10.0 percent — a value of exactly 10.0 counts as within tolerance — routes the order to `INVOICED`, actualizes the mirror line at the invoiced amount, and recomputes the account totals; this mirror update is applied whenever the call's current non-`SUPERSEDED` account carries the mirror line, whatever status the account is in. An absolute variance strictly greater than 10.0 percent routes the order to `DISPUTED` instead, and that branch cascades through three links: the order itself becomes `DISPUTED`; the mirror line moves to `DISPUTED` with the invoiced actual still recorded on it; and the account totals are recomputed, with an account in `FINAL` flipping to `DISPUTED`. A disputed order is not stuck — the owning `VendorRep` may reinvoice with a fresh `invoiced_cents` (likewise a non-negative integer), which stores the new amount, recomputes the variance, returns the order to `INVOICED`, updates the mirror line to `ACTUALIZED` at the new actual, and recomputes totals under the same rule — whenever a non-`SUPERSEDED` account carries the mirror line.

Finance closes the loop with the three-way match: an `AgencyFinance` controller matches an `INVOICED` order, and the same variance fork applies — this is a routing fork, not an error. Within tolerance, the order reaches `MATCHED`, its terminal state. Beyond tolerance, the order returns to `DISPUTED`, the mirror line moves to `DISPUTED`, the account totals are recomputed, and an account in `FINAL` flips to `DISPUTED`. An `AgencyOps` agent may cancel an order from `DRAFT`, `SENT`, or `ACKNOWLEDGED` — later states fail with `ERR_INVALID_STATE` — and the port-call cancellation cascade cancels the same three states; either way the mirror line is reversed (its estimate driven to zero) and the account totals are recomputed, again whenever a non-`SUPERSEDED` account carries the mirror line.

### 3.5. Service Orders: Pilotage, Towage, Line Boats, and Launches

Operational services are ordered through a **Service Order**. An `AgencyOps` agent supplies the `port_call_id`, the `kind` — `PILOT`, `TUG`, `LINEBOAT`, or `LAUNCH` — the shared `resource_unit` the service draws on (for example a named pilot boat or tug), the requested `window_start` and `window_end` with the start strictly earlier than the end (`ERR_WINDOW_INVALID`), the quoted `estimated_cents` at zero or more, and optionally a `quantity` of units that defaults to one and must be at least one. The vendor rule depends on kind: a `vendor_id` is required for `TUG`, `LINEBOAT`, and `LAUNCH` orders and must be omitted for `PILOT` orders, because pilots are port-authority resources; a violation is rejected with `ERR_VENDOR_KIND_MISMATCH`, and a referenced vendor that is not `ACTIVE` fails with `ERR_VENDOR_SUSPENDED`. New orders start `ORDERED`. When the call has a disbursement account in `PRO_FORMA`, `SENT_TO_PRINCIPAL`, or `FUNDED`, creation appends a mirror line at the quoted estimate — with the line's category mapped from the kind: `PILOT` to `PILOTAGE`, `TUG` to `TOWAGE`, `LINEBOAT` to `BERTH_HIRE`, and `LAUNCH` to `CREW_COSTS`, the line's `source_type` set to `SERVICE_ORDER`, and its `source_ref` recorded in the form ServiceOrder:<id> — and the account totals are recomputed. Order listings accept `port_call_id`, `vendor_id`, `resource_unit`, `kind`, and `status` filters.

Confirmation's actor also depends on kind. A `PILOT` order is confirmed by a `PortAuthority` officer; every other kind is confirmed by the `VendorRep` that owns the order's `vendor_id`. The endpoint admits both roles, but confirming through the wrong side is rejected with `ERR_CONFIRM_ROLE_MISMATCH`. Only an `ORDERED` order may be confirmed, and confirmation re-runs the buffer-inflated overlap check of §2.9 against every `CONFIRMED` or `IN_PROGRESS` order on the same `resource_unit` (`ERR_RESOURCE_UNIT_OVERLAP`).

Execution and completion are agency-driven. An `AgencyOps` agent starts a `CONFIRMED` order once the logical clock has reached the instant sixty minutes before `window_start`; earlier attempts fail with `ERR_WINDOW_NOT_STARTED`. Completing an `IN_PROGRESS` order carries the `actual_cents` the service actually cost, supplied as a non-negative integer: the mirror line's actual is set to that amount and the line becomes `ACTUALIZED`, with the account totals recomputed, whenever the account is in `PRO_FORMA`, `SENT_TO_PRINCIPAL`, or `FUNDED`; against a later-stage account the value is recorded on the order and the line keeps it for the next refinalization.

Cancellation carries the late fee. An `AgencyOps` agent may cancel from `ORDERED` or `CONFIRMED` — other states fail with `ERR_INVALID_STATE` — and the port-call cascade cancels the same two states. A direct cancellation made strictly later than two hours before `window_start` incurs a `cancellation_fee_cents` of one quarter of the order's `estimated_cents`, rounded half-up to integer cents; a cancellation exactly two hours before the window is not late, and cascade cancellations always produce a zero fee regardless of the clock. In every case the mirror line is reversed, its `estimated_cents` driven to zero; when a positive fee was charged and the account is in `PRO_FORMA`, `SENT_TO_PRINCIPAL`, or `FUNDED`, a `CANCELLATION_FEE` line is appended to the account with `source_type` `MANUAL`, null `source_ref` and `tariff_id`, an `estimated_cents` of zero, `actual_cents` equal to the fee, and status `ACTUALIZED`; and the account totals are recomputed.

### 3.6. Crew Changes, Shore Passes, and Husbandry Cases

A `CrewingAgent` registers each crew movement with the `port_call_id` it belongs to, the crew member's `full_name`, the ISO `nationality` code, the `passport_no`, the `passport_expiry` date, the `direction` — `ON_SIGNER` or `OFF_SIGNER` — and the `requires_visa` flag that selects the documentation branch. Movements start in `REQUESTED`. Document verification moves a `REQUESTED` movement to `DOCS_VERIFIED` and enforces passport validity: the `passport_expiry` must be strictly later than the parent call's `etd`, failing which verification is rejected with `ERR_PASSPORT_EXPIRY_INVALID`. Crew-change listings accept `port_call_id`, `status`, and `direction` filters.

The visa branch forks on `requires_visa`. Requesting a visa is only meaningful when the flag is set — a request on a movement with `requires_visa` false is rejected with `ERR_VISA_NOT_REQUIRED` — and it moves the movement from `DOCS_VERIFIED` to `VISA_PENDING`. A `PortAuthority` officer then grants the visa, recording the supplied `visa_reference` and moving the movement to `VISA_GRANTED`.

Shore-pass issuance by a `CrewingAgent` carries the mirrored branch rule and a re-issue path. From `DOCS_VERIFIED`, issuance is allowed only when no visa is required; attempting it while `requires_visa` is true fails with `ERR_VISA_REQUIRED`. From `VISA_GRANTED`, issuance proceeds directly. And from `PASS_EXPIRED`, a fresh pass may be issued to replace the expired one. In all three cases the supplied `shore_pass_expires_at` must lie in the future of the logical clock, failing which the request is rejected with `ERR_SHORE_PASS_EXPIRED`, and issuance from any other state fails with `ERR_INVALID_STATE`. Issuance records `shore_pass_expires_at` on the movement. Thereafter the pass is lazily expired: on any read of the movement, and on any gate evaluation that consults it, a movement in `SHORE_PASS_ISSUED` whose `shore_pass_expires_at` the clock has passed flips to `PASS_EXPIRED`. Completion by a `CrewingAgent` requires the movement to read as `SHORE_PASS_ISSUED` after that lazy evaluation — an expired pass reads as `PASS_EXPIRED` and the completion fails with `ERR_INVALID_STATE`. A `CrewingAgent` may cancel a movement from `REQUESTED`, `DOCS_VERIFIED`, or `VISA_PENDING`; the port-call cancellation cascade additionally cancels movements in `VISA_GRANTED`, `SHORE_PASS_ISSUED`, and `PASS_EXPIRED`. `COMPLETED`, `CANCELLED`, and `REPATRIATED` are terminal.

Welfare events are tracked as **Husbandry Cases**. A `HusbandryOfficer` opens a case with the `port_call_id` it arises under, a `case_type` of `MEDICAL`, `REPATRIATION`, `DESERTION`, or `OTHER`, a `severity` of `ROUTINE`, `URGENT`, or `CRITICAL`, a free-text `summary`, and optionally the `crew_change_id` of the linked crew movement. Cases open in `OPEN` with `departure_waiver_granted` false. Beginning treatment moves a case from `OPEN` to `IN_TREATMENT`, and clearing resolves a case from either `OPEN` or `IN_TREATMENT` to `CLEARED`. Repatriation from `OPEN` or `IN_TREATMENT` requires a linked crew change — a case without one is rejected with `ERR_NO_LINKED_CREW_CHANGE` — and cascades: the linked movement moves to `REPATRIATED` from `DOCS_VERIFIED`, `VISA_GRANTED`, or `SHORE_PASS_ISSUED`, while a linked movement in `PASS_EXPIRED` — or already in `COMPLETED` or `CANCELLED` — is left untouched. Case listings accept `port_call_id`, `crew_change_id`, `status`, and `severity` filters. Because an open `CRITICAL` case blocks sailing per §3.3, an `AgencyAdmin` holds the escape hatch: granting the one-case departure waiver sets `departure_waiver_granted` true at any time, regardless of the case's status, letting record-sailing pass despite that case.

### 3.7. Cargo Documents and Bill of Lading Release

An `AgencyOps` agent registers each **Cargo Document** with the `port_call_id` it belongs to, a `doc_type` of `BILL_OF_LADING`, `CARGO_MANIFEST`, or `DELIVERY_ORDER`, the document's `bl_number`, the `consignee_name`, and optionally the `freight_paid` flag, which defaults to false when omitted. The `bl_number` is unique per port call among documents that have not reached a terminal state; a duplicate registration is rejected with `ERR_DUPLICATE_BL_NUMBER`. Documents start in `RECEIVED`. Document listings accept `port_call_id`, `status`, and `doc_type` filters.

Verification moves a document from `RECEIVED` to `VERIFIED` and requires the parent call to be editable — a call that is `CANCELLED` or `CLOSED` fails the attempt with `ERR_PORT_CALL_NOT_EDITABLE`. A verified document may be placed `ON_HOLD` and the hold later released, cycling back to `VERIFIED`. Release is the terminal act, moving a `VERIFIED` document to `RELEASED`, and it carries two gates: the parent call must be `ALONGSIDE` — an early release is rejected with `ERR_BL_RELEASE_TOO_EARLY` — and a `BILL_OF_LADING` may only be released when `freight_paid` is true, failing which the release is rejected with `ERR_FREIGHT_NOT_PAID`. Documents of the other two types carry no freight gate. A held document also blocks departure, per the sailing gates of §3.3.

### 3.8. The Disbursement Account: Estimates, Lines, and Funding

The **Disbursement Account** opens when an `AgencyOps` agent creates one for a `port_call_id`, carrying `expected_port_call_version` per §2.8. Exactly one non-`SUPERSEDED` account exists per call: creation supersedes any existing `PRO_FORMA` account of the same call, moving it to `SUPERSEDED` without carrying its lines over — the new account rebuilds from sources and manual lines — while creation against a call whose existing non-`SUPERSEDED` account has already moved past `PRO_FORMA` is rejected with `ERR_INVALID_STATE`. Creation records the caller's `X-User-ID` as `created_by_user_id` and bumps the port call's `version`. The new account starts in `PRO_FORMA`. When a `PUBLISHED` tariff exists for the call's `port_code` and the `PORT_DUES` component, creation also seeds a `PORT_DUES` line whose `source_type` is `TARIFF`, priced by the estimate variant of the port-dues calculation below, pinning that tariff on the line's `tariff_id`; when no such tariff exists, no line is seeded. Account listings accept `port_call_id` and `status` filters.

Tariffs enter the system through a `PortAuthority` officer, who publishes one with its `port_code`, its `component` — `PORT_DUES`, `BERTH_HIRE`, or `PILOTAGE` — a required though informational `effective_from`, the `night_surcharge_pct` and `hazmat_surcharge_pct` fractions, each a non-negative number, and the `gt_tiers` rate table: a non-empty list of bands in strictly ascending order, each with a positive, inclusive `gt_up_to` upper bound in gross tons and a non-negative `rate_cents` price in cents per gross-ton-day, where a null `gt_up_to` is permitted only on the final band and marks it unbounded; an invalid payload is rejected with `ERR_INVALID_REQUEST`. Publication supersedes prior publications of the same port and component per §2.10, and a read capability lists, for any tariff, the account lines that pin that tariff version, presented in `created_at` ascending order with ties broken by `category` ascending; tariff listings accept `port_code`, `component`, and `status` filters.

Port dues are priced per gross-ton-day against the tariff's marginal bands. The billable duration in days is the hours between the two bounding timestamps divided by twenty-four, rounded up to a whole number, with a minimum of one day: the estimate variant uses the projected `eta` and `etd`, while the final variant uses `actual_arrival_at` and `actual_sailed_at`. The bands are then walked in ascending order; for each band, the billable tonnage is the lesser of the vessel's `vessel_gt` and the band's upper bound, minus the accumulated upper bounds of all lower bands, and whenever that portion is positive it is multiplied by the band's `rate_cents` and added to the base, stopping once the full `vessel_gt` has been billed. Because each `gt_up_to` is inclusive, a vessel whose gross tonnage equals a band's upper bound bills that tonnage entirely within that band. The base is multiplied by the number of days, and two surcharges may apply to that product: when the arrival hour — the `eta` hour for the estimate variant, the `actual_arrival_at` hour for the final variant — falls at or after 18:00 UTC or before 06:00 UTC, the `night_surcharge_pct` fraction of the base is added; and when the call's `hazmat_flag` is set, the `hazmat_surcharge_pct` fraction of the base is added. The resulting line amount is rounded half-up to integer cents exactly once, at the line level. The estimate variant prices against the tariff pinned at account creation; the final variant, applied at sailing, prices against the tariff `PUBLISHED` at sailing time even if it supersedes the pinned one, so identical call data can legitimately produce different estimate and final figures when a tariff was republished mid-call or the actual duration differs from the projection. On a tariff-sourced line the `estimated_cents` is computed and pinned by this calculation and any client-supplied value is ignored; the estimate variant refreshes through the schedule patch of §3.1, which is itself restricted to `NOMINATED` and `PRE_ARRIVAL_FILED`.

Beyond the seeded port-dues line, an account accumulates mirror lines from service orders (§3.5) and purchase orders (§3.4) and accepts manual lines. An `AgencyOps` agent or an `AgencyFinance` controller may add a manual line while the account is in `PRO_FORMA`, `SENT_TO_PRINCIPAL`, or `FUNDED`, supplying a `category` — one of `PORT_DUES`, `PILOTAGE`, `TOWAGE`, `BERTH_HIRE`, `PROVISIONS`, `BUNKERS`, `REPAIRS`, `STORES`, `CREW_COSTS`, `CANCELLATION_FEE`, or `SUNDRY` — a free-text `description`, and an `estimated_cents` of zero or more; the line's `source_type` is `MANUAL`, its `source_ref` and `tariff_id` stay null, and the totals are recomputed. Every line moves between `ESTIMATED`, `ACTUALIZED`, and `DISPUTED`: a line actualizes when its source completes — a service order completing, a purchase order invoicing, the sailing-time port-dues actualization, or the account finalization of §3.9 — it moves to `DISPUTED` when a cost dispute references it or its purchase order branches to `DISPUTED`, and it returns to `ACTUALIZED` when the dispute resolves or the order is reinvoiced. An account's lines are always presented in `created_at` ascending order, ties broken by `category` ascending and then by insertion order.

The account's derived totals follow §2.11's pinned evaluation order. `total_estimated_cents` is the sum of every line's `estimated_cents` plus `agency_fee_estimated_cents`, and `advance_required_cents` is eighty percent of that total, rounded half-up to integer cents. The agency fee itself is two and a half percent of each line's amount with the rounding order pinned: each line's fee is rounded half-up to integer cents first, and the rounded per-line integers are then summed — summing first and rounding once is expressly not the rule, so two lines of 3333 cents each contribute 83 cents apiece for a 166-cent fee, never 167. All lines participate regardless of whether they are `ESTIMATED`, `ACTUALIZED`, or `DISPUTED`, and reversed lines with zero estimates contribute zero. The funding side tracks `advances_received_cents` as the sum of `amount_cents` over advances in `RECEIVED`, `APPLIED`, or `REFUNDED` — receipts are cumulative, so a refunded advance's original receipt stays in the figure and its return is tracked separately through `advances_refunded_cents`, which is what keeps `funding_available_cents` from ever going negative per §2.11 — `advances_applied_cents` as the sum of `applied_cents` over all advances, `advances_refunded_cents` as the sum of `refunded_cents` over all advances, and `funding_available_cents` as received minus applied minus refunded. Until finalization, `total_final_cents`, `agency_fee_final_cents`, `balance_due_cents`, and `finalized_by_user_id` remain null.

Sending is the act that exposes the pro-forma to the customer: an `AgencyOps` agent moves the account from `PRO_FORMA` to `SENT_TO_PRINCIPAL`, provided the parent call is not `CANCELLED` or `CLOSED` (`ERR_PORT_CALL_NOT_EDITABLE`).

Funding then arrives as **Funding Advances**. An `AgencyFinance` controller — or a `PrincipalRep`, which may fund only accounts belonging to its own principal, failing which the attempt is rejected with `ERR_NOT_RESOURCE_OWNER` — records an advance with a strictly positive `amount_cents`, but only while the account is in `SENT_TO_PRINCIPAL`, `FUNDED`, `FINAL`, or `DISPUTED`; against any other account status the creation fails with `ERR_INVALID_STATE`. The advance starts in `RECEIVED` with `received_at` stamped from the logical clock. The account's funding posture then derives automatically from the gate, which is re-evaluated on every totals recompute — advance creations, applications, and refunds as well as line mutations: whenever net funding — received minus refunded — reaches or exceeds `advance_required_cents`, an account in `SENT_TO_PRINCIPAL` moves to `FUNDED` on its own; and whenever net funding falls below the requirement, an account in `FUNDED` reverts to `SENT_TO_PRINCIPAL`. Advance listings accept `da_id` and `status` filters.

Two finance operations manage the cash. Applying an advance carries a payload `amount_cents` and requires the advance to be `RECEIVED` with the account in `FUNDED`, `FINAL`, or `DISPUTED` — any other combination fails with `ERR_INVALID_STATE` — and the amount must be positive and no greater than the advance's remaining unapplied, unrefunded balance (`ERR_APPLY_EXCEEDS_REMAINING`). The amount is added to `applied_cents`; when the applied portion reaches the full `amount_cents` the advance becomes `APPLIED`, otherwise it stays `RECEIVED`, and the account's funding fields are recomputed. Refunding requires the advance to be `RECEIVED` with the account in `SENT_TO_PRINCIPAL`, `FUNDED`, `FINAL`, or `DISPUTED`; the refund always returns the full unapplied remainder — `refunded_cents` becomes the `amount_cents` minus `applied_cents` — the advance becomes `REFUNDED`, the funding fields are recomputed, and a `FUNDED` account auto-reverts when the gate no longer holds. `APPLIED` and `REFUNDED` are the terminal advance states.

### 3.9. Finalization, Disputes, and Settlement

Final accounting begins once the vessel has sailed. An `AgencyFinance` controller finalizes an account in `SENT_TO_PRINCIPAL` or `FUNDED`, moving it to `FINAL`. Two guards stand in front: the parent call must be in `SAILED` — finalizing earlier is rejected with `ERR_PORT_CALL_NOT_SAILED` — and segregation of duties forbids the account's creator from finalizing it, so the acting `X-User-ID` must differ from the account's `created_by_user_id`, failing which the request is rejected with `ERR_SEGREGATION_OF_DUTIES`. Finalization actualizes every line still in `ESTIMATED`: service-order and purchase-order mirrors take their source's actual cost, counting zero when the source was cancelled or has no actual recorded yet — a purchase order delivered but not yet invoiced, or a service order not yet completed, actualizes its mirror to zero; manual lines carry their estimate forward as the actual; and the `PORT_DUES` line keeps the value computed at sailing — a `PORT_DUES` line still `ESTIMATED` at finalization (possible when the account was created only after sailing) is instead priced by the final variant at finalization time, against the tariff then `PUBLISHED` and falling back to the pinned tariff. The final-variant totals are then computed — `total_final_cents` as the sum of every line's `actual_cents` plus `agency_fee_final_cents`, the final fee following the same per-line rounding rule applied to signed actuals so that credit lines with negative actuals reduce the fee, and `balance_due_cents` as `total_final_cents` minus `advances_applied_cents` — and the actor is recorded as `finalized_by_user_id`.

The customer answers with **Cost Disputes**. A `PrincipalRep` raises a dispute with the disputed `da_id`, a strictly positive `amount_cents`, a free-text `reason`, and optionally a `da_line_id`; omitting the line disputes the whole account. The dispute's `principal_id` is taken from the caller's `X-User-ID`, and the caller must own the principal behind the account (`ERR_NOT_RESOURCE_OWNER`). The account must be in `FINAL` or `DISPUTED` — raising against any other status fails with `ERR_INVALID_STATE` — and the raising cascades: an account in `FINAL` flips to `DISPUTED`, and a referenced line in `ACTUALIZED` moves to `DISPUTED`. The dispute starts `RAISED`. Dispute listings accept `da_id`, `da_line_id`, `principal_id`, and `status` filters.

Review and resolution follow a fixed ladder. An `AgencyFinance` controller opens review (`RAISED` → `UNDER_REVIEW`), then either upholds or rejects, recording a `resolution_note` in both cases. Upholding applies the credit: when the dispute references a line, that line's `actual_cents` is reduced by the disputed amount but never below zero and the line returns to `ACTUALIZED`; when the dispute targets the whole account, a manual `SUNDRY` credit line with a zero `estimated_cents` and an `actual_cents` equal to the negative of the disputed amount is appended instead; and the account totals are recomputed in the final variant. Rejecting leaves the numbers untouched, returning any linked line to `ACTUALIZED` unchanged. A rejected dispute is not finished: the owning `PrincipalRep` may escalate it (`REJECTED` → `ESCALATED`), with ownership enforced as `ERR_NOT_RESOURCE_OWNER`. Escalated disputes land with an `AgencyAdmin`, whose resolution carries a `decision` and a `resolution_note`: an `ACCEPT` decision resolves the dispute as `RESOLVED_ACCEPTED` and applies the same credit mechanics as an uphold, while a `REJECT` decision resolves it as `RESOLVED_REJECTED` with any linked line returned to `ACTUALIZED` unchanged. `UPHELD`, `RESOLVED_ACCEPTED`, and `RESOLVED_REJECTED` are terminal.

Disputes force re-finalization rather than editing a closed account. An `AgencyFinance` controller refinalizes an account in `DISPUTED`, returning it to `FINAL`, only when no dispute of the account remains in `RAISED`, `UNDER_REVIEW`, or `ESCALATED` — open disputes fail the attempt with `ERR_DISPUTES_OPEN` — and the same segregation-of-duties guard applies against `created_by_user_id` (`ERR_SEGREGATION_OF_DUTIES`). Refinalization recomputes the final-variant totals with any upheld credits already applied to the lines and records the acting user as `finalized_by_user_id`.

Settlement closes the money loop. An `AgencyFinance` controller settles an account in `FINAL`, moving it to `SETTLED`, under two exact conditions: no advance of the account may still be `RECEIVED` holding an unapplied, unrefunded remainder — such an advance must first be applied or refunded, failing which settlement is rejected with `ERR_UNREFUNDED_ADVANCES` — and `balance_due_cents` must be exactly zero, meaning the applied advances equal the final total; a nonzero balance, in either direction, is rejected with `ERR_BALANCE_NOT_ZERO`, because exact equality, not mere sufficiency, is required. Only a `SETTLED` account lets the port call close, per §3.3.

## 4. Endpoint Definitions

Operations that create new resources return a `201 Created` status code — this covers the collection-creating endpoints for principals, port calls, notifications, berth windows, service orders, crew changes, vendors, purchase orders, cargo documents, tariffs, disbursement accounts, account lines, funding advances, cost disputes, and husbandry cases. All other operations — reads, state transitions, and modifications such as the port-call patch — return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/principals` | Create a principal | AgencyAdmin |
| GET | `/principals` | List principals (paginated) | Any authenticated role |
| GET | `/principals/{id}` | Get a principal | Any authenticated role |
| POST | `/principals/{id}/suspend` | Suspend a principal (blocks new port calls) | AgencyAdmin |
| POST | `/principals/{id}/reinstate` | Reinstate a principal | AgencyAdmin |
| GET | `/principals/{id}/exposure` | Computed credit exposure (forward and cash-basis variants) | Any authenticated role |
| POST | `/port-calls` | Create a port call in NOMINATED; credit gate on the principal | AgencyOps |
| GET | `/port-calls` | List port calls | Any authenticated role |
| GET | `/port-calls/{id}` | Get a port call | Any authenticated role |
| PATCH | `/port-calls/{id}` | Update schedule/cargo fields; OCC-guarded; only in NOMINATED or PRE_ARRIVAL_FILED | AgencyOps |
| POST | `/port-calls/{id}/file-pre-arrival` | File the pre-arrival package (deadline twenty-four hours before ETA) | AgencyOps |
| POST | `/port-calls/{id}/grant-clearance` | Port authority grants clearance to enter | PortAuthority |
| POST | `/port-calls/{id}/record-arrival` | Record actual arrival onto an occupied berth window | AgencyOps |
| POST | `/port-calls/{id}/record-sailing` | Record sailing; full gate battery; releases the berth; actualizes the PORT_DUES line | AgencyOps |
| POST | `/port-calls/{id}/close` | Close the call after account settlement | AgencyFinance |
| POST | `/port-calls/{id}/cancel` | Cancel the call; cascading reversal over windows, filings, crew, orders, and lines | AgencyOps, AgencyAdmin |
| POST | `/authority-notifications` | Create a notification in DRAFT for a port call | AgencyOps |
| GET | `/authority-notifications` | List notifications | Any authenticated role |
| GET | `/authority-notifications/{id}` | Get a notification | Any authenticated role |
| POST | `/authority-notifications/{id}/submit` | Submit the filing to the authority | AgencyOps |
| POST | `/authority-notifications/{id}/acknowledge` | Authority acknowledges with a reference | PortAuthority |
| POST | `/authority-notifications/{id}/reject` | Authority rejects with a reason | PortAuthority |
| POST | `/authority-notifications/{id}/resubmit` | Resubmit after rejection (bumps the revision count) | AgencyOps |
| POST | `/berth-windows` | Request a berth window (overlap checked at confirm) | AgencyOps |
| GET | `/berth-windows` | List berth windows | Any authenticated role |
| GET | `/berth-windows/{id}` | Get a berth window | Any authenticated role |
| POST | `/berth-windows/{id}/confirm` | Authority confirms; half-open overlap re-checked | PortAuthority |
| POST | `/berth-windows/{id}/occupy` | Mark occupied; requires HARBOR_MASTER acknowledgment | AgencyOps |
| POST | `/berth-windows/{id}/release` | Release an occupied berth | AgencyOps |
| POST | `/berth-windows/{id}/cancel` | Cancel a non-terminal window | AgencyOps |
| POST | `/service-orders` | Order pilot, tug, lineboat, or launch service on a resource unit | AgencyOps |
| GET | `/service-orders` | List service orders | Any authenticated role |
| GET | `/service-orders/{id}` | Get a service order | Any authenticated role |
| POST | `/service-orders/{id}/confirm` | Confirm an order; actor depends on kind; buffered overlap re-checked | PortAuthority, VendorRep |
| POST | `/service-orders/{id}/start` | Start a confirmed service | AgencyOps |
| POST | `/service-orders/{id}/complete` | Complete with the actual cost; actualizes the account line | AgencyOps |
| POST | `/service-orders/{id}/cancel` | Cancel an order; late fee inside the two-hour cutoff | AgencyOps |
| POST | `/crew-changes` | Register a crew on/off movement | CrewingAgent |
| GET | `/crew-changes` | List crew changes | Any authenticated role |
| GET | `/crew-changes/{id}` | Get a crew change | Any authenticated role |
| POST | `/crew-changes/{id}/verify-docs` | Verify documents; passport validity gate | CrewingAgent |
| POST | `/crew-changes/{id}/request-visa` | Request a visa (requires-visa branch) | CrewingAgent |
| POST | `/crew-changes/{id}/grant-visa` | Authority grants the visa | PortAuthority |
| POST | `/crew-changes/{id}/issue-shore-pass` | Issue a shore pass (also re-issue after expiry) | CrewingAgent |
| POST | `/crew-changes/{id}/complete` | Complete the movement | CrewingAgent |
| POST | `/crew-changes/{id}/cancel` | Cancel the movement | CrewingAgent |
| POST | `/vendors` | Register a vendor | AgencyAdmin |
| GET | `/vendors` | List vendors | Any authenticated role |
| GET | `/vendors/{id}` | Get a vendor | Any authenticated role |
| POST | `/vendors/{id}/suspend` | Suspend a vendor | AgencyAdmin |
| POST | `/vendors/{id}/reinstate` | Reinstate a vendor | AgencyAdmin |
| POST | `/purchase-orders` | Create a purchase order in DRAFT; vendor, category, and referential gates | AgencyOps |
| GET | `/purchase-orders` | List purchase orders | Any authenticated role |
| GET | `/purchase-orders/{id}` | Get a purchase order | Any authenticated role |
| POST | `/purchase-orders/{id}/send` | Send the order to the vendor | AgencyOps |
| POST | `/purchase-orders/{id}/acknowledge` | Vendor acknowledges the order | VendorRep |
| POST | `/purchase-orders/{id}/deliver` | Vendor marks the order delivered | VendorRep |
| POST | `/purchase-orders/{id}/invoice` | Vendor invoices; variance fork to INVOICED or DISPUTED | VendorRep |
| POST | `/purchase-orders/{id}/reinvoice` | Vendor reinvoices a disputed order | VendorRep |
| POST | `/purchase-orders/{id}/match` | Finance three-way match; fork to MATCHED or DISPUTED | AgencyFinance |
| POST | `/purchase-orders/{id}/cancel` | Cancel the order; reverses the account line mirror | AgencyOps |
| POST | `/cargo-documents` | Register a cargo document | AgencyOps |
| GET | `/cargo-documents` | List cargo documents | Any authenticated role |
| GET | `/cargo-documents/{id}` | Get a cargo document | Any authenticated role |
| POST | `/cargo-documents/{id}/verify` | Verify the document | AgencyOps |
| POST | `/cargo-documents/{id}/hold` | Place a hold | AgencyOps |
| POST | `/cargo-documents/{id}/release-hold` | Lift the hold | AgencyOps |
| POST | `/cargo-documents/{id}/release` | Release the document (B/L requires ALONGSIDE and freight paid) | AgencyOps |
| POST | `/tariffs` | Publish a tariff; supersedes published tariffs of the same port and component | PortAuthority |
| GET | `/tariffs` | List tariffs | Any authenticated role |
| GET | `/tariffs/{id}` | Get a tariff | Any authenticated role |
| GET | `/tariffs/{id}/da-lines` | List the account lines pinning this tariff version | Any authenticated role |
| POST | `/disbursement-accounts` | Create an account in PRO_FORMA; supersedes an existing PRO_FORMA; OCC on the port call | AgencyOps |
| GET | `/disbursement-accounts` | List disbursement accounts | Any authenticated role |
| GET | `/disbursement-accounts/{id}` | Get an account with computed totals | Any authenticated role |
| POST | `/disbursement-accounts/{id}/send` | Send the pro-forma to the principal | AgencyOps |
| GET | `/disbursement-accounts/{id}/lines` | List account lines (created_at ascending, category ascending) | Any authenticated role |
| POST | `/disbursement-accounts/{id}/lines` | Add a manual line while the account is editable | AgencyOps, AgencyFinance |
| POST | `/disbursement-accounts/{id}/finalize` | Finalize after sailing; segregation of duties enforced | AgencyFinance |
| POST | `/disbursement-accounts/{id}/refinalize` | Re-finalize after disputes are resolved | AgencyFinance |
| POST | `/disbursement-accounts/{id}/settle` | Settle when the balance is zero and no advance holds a remainder | AgencyFinance |
| POST | `/disbursement-accounts/{id}/advances` | Record a funding advance receipt | AgencyFinance, PrincipalRep |
| GET | `/funding-advances` | List funding advances | Any authenticated role |
| GET | `/funding-advances/{id}` | Get a funding advance | Any authenticated role |
| POST | `/funding-advances/{id}/apply` | Apply (part of) an advance against the final account | AgencyFinance |
| POST | `/funding-advances/{id}/refund` | Refund the unapplied remainder | AgencyFinance |
| POST | `/cost-disputes` | Raise a dispute against an account or a single line | PrincipalRep |
| GET | `/cost-disputes` | List disputes | Any authenticated role |
| GET | `/cost-disputes/{id}` | Get a dispute | Any authenticated role |
| POST | `/cost-disputes/{id}/start-review` | Finance opens review | AgencyFinance |
| POST | `/cost-disputes/{id}/uphold` | Finance upholds; credit applied to the line or the account | AgencyFinance |
| POST | `/cost-disputes/{id}/reject` | Finance rejects the dispute | AgencyFinance |
| POST | `/cost-disputes/{id}/escalate` | Principal escalates a rejected dispute | PrincipalRep |
| POST | `/cost-disputes/{id}/resolve` | Admin resolves an escalated dispute | AgencyAdmin |
| POST | `/husbandry-cases` | Open a husbandry case (medical, repatriation, desertion, other) | HusbandryOfficer |
| GET | `/husbandry-cases` | List husbandry cases | Any authenticated role |
| GET | `/husbandry-cases/{id}` | Get a husbandry case | Any authenticated role |
| POST | `/husbandry-cases/{id}/begin-treatment` | Begin treatment | HusbandryOfficer |
| POST | `/husbandry-cases/{id}/clear` | Clear the case | HusbandryOfficer |
| POST | `/husbandry-cases/{id}/repatriate` | Repatriate; cascades to the linked crew change | HusbandryOfficer |
| POST | `/husbandry-cases/{id}/waive-departure-hold` | Grant the one-case departure waiver | AgencyAdmin |
| POST | `/_clock/set_current_utc` | Set the logical clock (startup default 2026-05-01T00:00:00Z) | AgencyAdmin |

## 5. Error Code Catalogue

Trigger conditions for each error are defined in the workflows of Sections 2 and 3; this catalogue enumerates only the identifiers and their HTTP status codes.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_NOT_RESOURCE_OWNER` | 403 Forbidden |
| `ERR_CONFIRM_ROLE_MISMATCH` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_BERTH_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_RESOURCE_UNIT_OVERLAP` | 409 Conflict |
| `ERR_DUPLICATE_NOTIFICATION_TYPE` | 409 Conflict |
| `ERR_DUPLICATE_BL_NUMBER` | 409 Conflict |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_PRE_ARRIVAL_DEADLINE_MISSED` | 422 Unprocessable Content |
| `ERR_WINDOW_INVALID` | 422 Unprocessable Content |
| `ERR_WINDOW_NOT_STARTED` | 422 Unprocessable Content |
| `ERR_PASSPORT_EXPIRY_INVALID` | 422 Unprocessable Content |
| `ERR_SHORE_PASS_EXPIRED` | 422 Unprocessable Content |
| `ERR_NOTIFICATIONS_OUTSTANDING` | 422 Unprocessable Content |
| `ERR_HM_ACK_OUTSTANDING` | 422 Unprocessable Content |
| `ERR_BERTH_WINDOW_MISMATCH` | 422 Unprocessable Content |
| `ERR_BERTH_NOT_OCCUPIED` | 422 Unprocessable Content |
| `ERR_OPEN_CREW_CHANGES` | 422 Unprocessable Content |
| `ERR_CARGO_DOCS_ON_HOLD` | 422 Unprocessable Content |
| `ERR_BL_RELEASE_TOO_EARLY` | 422 Unprocessable Content |
| `ERR_FREIGHT_NOT_PAID` | 422 Unprocessable Content |
| `ERR_VISA_NOT_REQUIRED` | 422 Unprocessable Content |
| `ERR_VISA_REQUIRED` | 422 Unprocessable Content |
| `ERR_PORT_CALL_NOT_EDITABLE` | 422 Unprocessable Content |
| `ERR_PORT_CALL_NOT_SAILED` | 422 Unprocessable Content |
| `ERR_SEGREGATION_OF_DUTIES` | 422 Unprocessable Content |
| `ERR_DISPUTES_OPEN` | 422 Unprocessable Content |
| `ERR_DA_NOT_SETTLED` | 422 Unprocessable Content |
| `ERR_DA_NOT_SENT` | 422 Unprocessable Content |
| `ERR_NO_LINKED_CREW_CHANGE` | 422 Unprocessable Content |
| `ERR_PRINCIPAL_SUSPENDED` | 422 Unprocessable Content |
| `ERR_VENDOR_SUSPENDED` | 422 Unprocessable Content |
| `ERR_VENDOR_CATEGORY_MISMATCH` | 422 Unprocessable Content |
| `ERR_VENDOR_KIND_MISMATCH` | 422 Unprocessable Content |
| `ERR_FUNDING_SHORTFALL` | 422 Unprocessable Content |
| `ERR_CREDIT_LIMIT_EXCEEDED` | 422 Unprocessable Content |
| `ERR_UNREFUNDED_ADVANCES` | 422 Unprocessable Content |
| `ERR_BALANCE_NOT_ZERO` | 422 Unprocessable Content |
| `ERR_APPLY_EXCEEDS_REMAINING` | 422 Unprocessable Content |
| `ERR_OPEN_CRITICAL_HUSBANDRY` | 422 Unprocessable Content |
