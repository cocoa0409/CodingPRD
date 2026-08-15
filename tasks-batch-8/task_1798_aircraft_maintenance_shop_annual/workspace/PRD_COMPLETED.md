# Aircraft Maintenance Shop & Annual Inspection API — Product Requirements Document

## 1. Introduction

A certificated repair station lives and dies by its paper trail. Every annual or 100-hour inspection produces a chain of regulated artifacts: a scoped work order, an item-by-item inspection checklist, a discrepancy list that the aircraft owner must disposition, applicability determinations for airworthiness directives and service bulletins, parts with traceability documents, logbook entries signed by a properly certificated mechanic, and finally a return-to-service statement. Each artifact carries legal weight, and each hand-off — mechanic to owner, parts clerk to mechanic, inspector to verifier — is a place where money and safety can quietly fall out of sync. The shop also runs a business on top of that compliance spine: hangar space is billed by the calendar day, labor is billed either by the clock or by published flat rates, shop supplies are surcharged in tiers, and the shop warrants its maintenance work for a fixed window after the aircraft leaves.

This document specifies the Aircraft Maintenance Shop & Annual Inspection API, the system of record for that entire operation. The API manages owners, aircraft, mechanics, hangar slots, work orders and their checklists, discrepancies and owner decisions, directives, parts, labor entries, logbook entries, and invoices, all mounted under the `/api` URL prefix. It derives each aircraft's airworthiness posture continuously from open directives and open discrepancies, enforces segregation of duties between rectification and verification, prices work under either hourly or flat-rate models down to the cent, and serializes the two writes most prone to stale reads — work-order intake and owner decisions — through optimistic concurrency control. A shop-controlled logical clock underpins every server-stamped timestamp so that billing-day, warranty, and scheduling semantics are deterministic.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and boilerplate that apply to every resource and every endpoint of the API.

### 2.1. User and Role-Based Access Control

All interactions with the API are authenticated through two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring their operational capacity. The system recognizes exactly four roles: `ShopManager`, `Mechanic`, `Owner`, and `PartsClerk`. A request missing either header, or presenting a role outside this enumeration, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is authenticated but not permitted to invoke the target endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

Role identity is resolved as follows. When `X-User-Role` is `Mechanic`, `X-User-ID` is the `id` of the acting `Mechanic` record; ownership and identity checks on any resource that references a mechanic — such as labor postings, checklist recordings, and logbook signatures — compare the resource's mechanic field to `X-User-ID`. The work-order transitions driven in the `Mechanic` role — start, complete-inspection, submit-for-approval, begin-work, ready-for-rts, and return-to-service — resolve that acting record from `X-User-ID`: an identifier matching no `Mechanic` row fails with `ERR_NOT_FOUND` (HTTP 404), and a resolved record whose `status` is `INACTIVE` fails the transition with `ERR_INVALID_STATE` (HTTP 409). When `X-User-Role` is `Owner`, `X-User-ID` is the `id` of the acting `Owner` record; ownership checks compare an aircraft's registered `owner_id` to `X-User-ID`, which is what restricts discrepancy decisions, inspection reopens, and invoice payments to the aircraft's actual owner. When `X-User-Role` is `ShopManager`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it against any entity's `id`. The same is true when `X-User-Role` is `PartsClerk`: the identifier is opaque, recorded nowhere as a foreign key, and never compared to an entity `id`.

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

Endpoints that return lists of resources accept two query parameters. The `limit` parameter sets the maximum number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter sets the number of items skipped and defaults to 0. A non-integer `limit` or `offset`, a `limit` outside [1, 100], or a negative `offset` is rejected with `ERR_VALIDATION` (HTTP 400).

Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order, with ties on `created_at` broken by creation (insertion) order.

Paginated list responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the response envelope, where `has_more` is true exactly when `offset` plus the number of rows returned is less than `total_count`. In addition to pagination, many list endpoints accept resource-specific filters — for example `status`, `owner_id`, `airworthiness_posture`, `certificate_class`, `hangar_code`, `aircraft_id`, `work_order_id`, `hangar_slot_id`, `opened_by_mechanic_id`, `result`, `inspected_by_mechanic_id`, `mechanic_id`, `checklist_item_id`, `decided_by_owner_id`, `compliance_status`, `evaluated_by_mechanic_id`, `discrepancy_id`, and `signed_by_mechanic_id` — each narrowing the listing to rows matching the supplied value.

### 2.4. Common Resource Properties

Nine primary resources — Owner, Aircraft, Mechanic, HangarSlot, WorkOrder, Discrepancy, Directive, Part, and Invoice — share a standard set of system-managed fields:

- **`id` (string):** a unique, server-minted identifier formatted as a UUID, with no type prefix.
- **`created_at` (string):** an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- **`updated_at` (string):** an ISO 8601 UTC timestamp refreshed on every mutation of the resource.
- **`version` (integer):** a system-managed integer starting at 1 at creation and incremented by one on every mutation, including automatic state transitions and recomputations of derived fields performed by the server.

Three resources are deliberately lighter. ChecklistItem, LaborEntry, and LogbookEntry carry only `id` and `created_at`; both `updated_at` and `version` are absent from them. A checklist item's result is recorded onto the item without versioning, a labor entry's bookkeeping runs through its `status` field rather than a version counter, and a logbook entry is immutable once appended, so there is nothing to version.

### 2.5. Monetary Precision and Rounding

Every monetary amount in the system is stored and returned as an integer number of cents — rates, estimates, prices, fees, taxes, and totals alike. All rounding follows the round-half-up rule: a fractional cent of one half or more rounds up, anything less rounds down. Where a calculation aggregates many monetary components, the rounding granularity is pinned per component — per labor entry and per part line — and the rounded components are then summed; the system never sums unrounded values and rounds once at the end. Fee and tax computations that consume an aggregate (the shop-supplies surcharge and the sales tax) operate on the already-rounded aggregate and are themselves rounded half up to whole cents. Monetary values appear in API responses as plain numbers, not strings.

### 2.6. Optimistic Concurrency Control

Two write operations are protected by optimistic concurrency control, and they are the only endpoints in the API that accept a version field.

Opening a work order requires the client to supply `expected_hangar_slot_version`, carrying the `version` of the target hangar slot as the client last observed it. If the slot's current `version` no longer matches — because another writer has advanced the slot since the client read it — the request is rejected with `ERR_STALE_VERSION` (HTTP 412), and the client must re-read the slot before retrying.

Posting an owner decision on a discrepancy requires the client to supply `expected_discrepancy_version`, carrying the `version` of the discrepancy as the client last observed it. If the discrepancy's current `version` has advanced beyond that value, the decision is rejected with `ERR_STALE_VERSION` (HTTP 412), forcing the client to re-read the discrepancy rather than decide on a finding that has changed underfoot.

On work-order intake the version check runs after the referenced aircraft, hangar slot, and mechanic have all been resolved; on the decision endpoint it runs after payload validation and before the discrepancy's state-permissibility check, so a stale `expected_discrepancy_version` surfaces `ERR_STALE_VERSION` even when the discrepancy has already left `PENDING_OWNER_DECISION`. No other endpoint accepts or requires a version field; optimistic concurrency applies nowhere else.

### 2.7. The Logical Clock

The shop runs on a logical UTC clock rather than the host's wall clock. At server startup the logical clock reads exactly 2026-08-01T00:00:00Z, and it never falls back to wall-clock time thereafter. A `ShopManager`-only capability sets the logical clock to a supplied `to_iso8601` instant — any parseable ISO 8601 instant is accepted, forward or backward, with no monotonicity constraint — and this is the only way time moves. Every server-stamped timestamp in the system — logbook signing times, return-to-service instants, and the warranty windows derived from them — is drawn from this logical clock; the one exception is the response envelope's `api_request_timestamp`, which is drawn from the host wall clock.

### 2.8. Hierarchical Consistency and Cascading Side Effects

The system maintains consistency across its hierarchy by cascading state changes rather than leaving reconciliation to clients. A hangar slot's occupancy follows the work order booked against it: the slot becomes occupied when work begins and is released when the aircraft returns to service. A work order's derived counters — its open and verified discrepancy counts and its accumulated labor — are recomputed by the server whenever the underlying discrepancies or labor entries change. An aircraft's airworthiness posture is recomputed whenever any discrepancy, directive, or work order touching that aircraft changes. Where a transition's completion criteria become satisfied as a side effect of another write — most notably the last pending owner decision resolving — the server advances the parent work order automatically, with no separate client call. Every such server-side mutation on a versioned resource refreshes its `updated_at` and increments its `version`, so a client holding an earlier `version` always has an accurate signal that the resource moved.

### 2.9. Nested Resource Retrieval and the Validation Pipeline

Requests that target nested resources are validated left to right along the path: each path identifier must resolve to an existing row before the next is examined, and the first identifier that does not resolve fails the request with `ERR_NOT_FOUND` (HTTP 404). A request to record a result on a checklist item, for example, resolves the work order before it ever looks for the item; a missing work order surfaces as `ERR_NOT_FOUND` regardless of whether the item exists elsewhere. The same existence discipline applies to foreign-key references in request bodies.

Every request passes through a fixed validation pipeline. Authentication is checked first (presence of headers and a known role), authorization second (the role's permission for the endpoint), existence third (path identifiers and foreign keys), and state permissibility fourth — an action attempted against an entity that is not in a state allowing that transition is rejected with `ERR_INVALID_STATE` (HTTP 409). Only then do the domain business rules run, and their relative order is pinned so that overlapping failures always surface the same error: the owner-decision requirement is evaluated first among business rules, then the regulatory airworthiness gate, then hangar-slot overlap, then mechanic overbooking, then parts traceability, then the invoice lock, and finally slot-window validity. Consequently, reserving a hangar slot whose interval both overlaps another booking and exceeds the permitted window reports the overlap, and posting labor to an invoice-locked work order by an overbooked mechanic reports the overbooking. Independently of this pipeline, a request whose payload is malformed — a missing required field, an invalid enum value, a part `quantity` below one, or a labor `duration_tenths` that is not a positive multiple of three — is rejected outright with `ERR_VALIDATION` (HTTP 400).

## 3. Business Logic & Workflows

### 3.1. Principals of Record: Owners, Aircraft, and Mechanics

Before any maintenance can be booked, the shop registers its principals. A `ShopManager` registers an owner with the owner's `full_name`, `email`, and `phone`; the `email` must be unique across all owners, with a duplicate rejected by `ERR_VALIDATION` (HTTP 400). Registration may optionally set `approval_cap_cents`, the per-discrepancy pre-authorization ceiling; when omitted it defaults to 50,000 cents (five hundred dollars), meaning any single repair finding estimated at or above that amount will require the owner's explicit decision rather than flowing through automatically. An owner's `status` begins as `ACTIVE`; the `SUSPENDED` value exists in the model, but no API operation changes an owner's status and the field gates nothing.

Aircraft are registered against a registered owner via the `owner_id` field, along with the FAA registration `tail_number` — unique across the fleet, with a duplicate rejected by `ERR_VALIDATION` (HTTP 400) — the `make_model`, and `total_time_hours`, the airframe total time expressed in tenths of an hour (accepted as any JSON number and echoed verbatim). Every aircraft carries a computed `airworthiness_posture`, one of `AIRWORTHY`, `RESTRICTED`, or `GROUNDED`, together with a computed `posture_reason` summarizing in human-readable terms the rule that produced the current posture. A freshly registered aircraft has no open findings and starts `AIRWORTHY`. An owner can review the fleet tied to their account through the owner's aircraft listing, which reaches aircraft in reverse through the registered `owner_id`.

A `ShopManager` also registers each mechanic with `full_name`, a unique `certificate_number` (a duplicate is rejected by `ERR_VALIDATION`, HTTP 400), a `certificate_class` of either `AP` (Airframe & Powerplant) or `IA` (Inspection Authorization), and the shop's billing rate for that mechanic, `hourly_rate_cents`. A mechanic's `status` begins `ACTIVE`, and no API operation changes it; an `INACTIVE` mechanic may not drive work-order transitions, failing with `ERR_INVALID_STATE` (HTTP 409) per §2.1. The certificate class matters well beyond the roster: inspection authorizations gate annual sign-offs, return-to-service of annual-scope work, and independent verification, as later sections describe.

### 3.2. Booking the Hangar and Opening a Work Order

Hangar time is a scarce, billable resource, so the shop books it explicitly. A `ShopManager` reserves a hangar slot by supplying the physical `hangar_code`, the occupying `aircraft_id`, the slot bounds `starts_at` and `ends_at` in UTC, and the `daily_rate_cents` billed per day; the supplied `starts_at` and `ends_at` strings are stored and echoed verbatim in responses. A slot's interval is half-open: it covers the instant `starts_at` up to but not including `ends_at`. Two structural rules guard reservations. First, `ends_at` must be strictly later than `starts_at`, and the total duration may not exceed thirty days; a violation is rejected with `ERR_INVALID_WINDOW` (HTTP 422). Second, for the same `hangar_code`, the new interval must not intersect any existing slot in `RESERVED` or `OCCUPIED` status — though intervals that merely touch, one's `ends_at` equal to the other's `starts_at`, are permitted back-to-back; an intersection is rejected with `ERR_SLOT_OVERLAP` (HTTP 409). Per the pipeline in §2.9, the overlap screen is evaluated ahead of the window screen when both could fire. A new slot is `RESERVED`.

With a slot booked, a `ShopManager` opens a work order by supplying the `aircraft_id`, the `hangar_slot_id` of the reserved slot, the `opened_by_mechanic_id` of the mechanic taking responsibility, the `scope_type` — `ANNUAL`, `HUNDRED_HOUR`, or `UNSCHEDULED` — and the `pricing_mode`, which commits the order to either `HOURLY` billing of actual labor or `FLAT_RATE` billing of published task prices. Because intake is the moment two dispatchers most often collide over the same slot, this creation is one of the two optimistic-concurrency writes in §2.6: the request must carry `expected_hangar_slot_version` matching the slot's current `version`, and a mismatch is rejected with `ERR_STALE_VERSION`. Successfully opening the work order itself advances the linked slot's `version` by one, so any other client holding the slot's old version is immediately stale. Opening performs no check on the slot's status or aircraft and does not prevent a second work order from referencing the same slot; those conditions are enforced at scheduling. A new work order is `DRAFT`.

Scheduling moves the work order from `DRAFT` to `SCHEDULED`. A `ShopManager` may schedule only when three conditions hold: the linked hangar slot is still `RESERVED`, the slot's aircraft matches the work order's aircraft, and no other work order for the same aircraft is currently `IN_PROGRESS` or `WORK_IN_PROGRESS` — the shop never runs two concurrent maintenance streams on one airframe; a failure of any of the three is rejected with `ERR_INVALID_STATE` (HTTP 409). A work order still in `DRAFT` may instead be cancelled by a `ShopManager`, moving it to `CANCELLED`; cancellation cascades to the linked hangar slot, moving it to `CANCELLED` as well. A hangar slot reaches `CANCELLED` only through the cancellation of its linked work order; the API exposes no independent slot-cancellation operation.

Work begins when a `Mechanic` starts the order, moving `SCHEDULED` to `IN_PROGRESS`. The acting mechanic must be `ACTIVE` and hold an `AP` or `IA` certificate, and the linked slot must be `RESERVED` or already `OCCUPIED` — a slot in any other status fails the start with `ERR_INVALID_STATE` (HTTP 409). Starting cascades: the slot moves to `OCCUPIED`, and the aircraft's `airworthiness_posture` is recomputed — although merely entering maintenance does not itself ground an aircraft. `CANCELLED` and, later, `CLOSED` are the work order's terminal states.

### 3.3. Running the Inspection: Checklists and Findings

While the order is in progress, the assigned mechanics work the inspection checklist. A `Mechanic` adds each checklist item with an `item_code` (a reference such as C-142-ENG), the task `description`, and the `flat_rate_cents` published price for the task — the price billed for this item when the work order runs under `FLAT_RATE`. Items may be added while the order stands `DRAFT`, `SCHEDULED`, or `IN_PROGRESS`; adding an item in any later state is rejected with `ERR_INVALID_STATE` (HTTP 409). An item's `result` begins `PENDING`, and its `inspected_by_mechanic_id` stays null until a result is recorded. Checklist items are retrievable both within their work order and through shop-wide listings filterable by `work_order_id`, `result`, or `inspected_by_mechanic_id`, and each item is individually addressable by its own id — the recording path addresses the item as `item_id` nested under its work order.

As tasks are accomplished, a `Mechanic` records each item's outcome: a `result` of `PASS`, `FAIL`, or `NA`, together with the `inspected_by_mechanic_id` of whoever made the call. Recording is permitted only while the work order stands `IN_PROGRESS` — otherwise `ERR_INVALID_STATE` (HTTP 409) — and may overwrite a result recorded earlier. A `FAIL` does not immediately spawn paperwork — but it flags the item, and at inspection completion the system ensures every failed item is matched by a discrepancy.

Completing the inspection moves the work order from `IN_PROGRESS` to `INSPECTION_COMPLETE`. The gate is strict: every checklist item must have a recorded `result` of `PASS`, `FAIL`, or `NA` with zero items left `PENDING`, and an `ANNUAL`-scope order must have at least one item whose result is not `NA` — an annual that inspected nothing is rejected. Either violation surfaces as `ERR_CHECKLIST_INCOMPLETE` (HTTP 422). On completion, the system auto-creates an `OPEN` discrepancy for every `FAIL` item that no existing discrepancy (of any status) references, copying the item's `description`, assigning severity `AIRWORTHINESS` and an `estimated_cost_cents` of 50,000 cents, and setting `requires_owner_decision` by comparing that estimate against the aircraft owner's cap at that instant; the work order's `open_discrepancy_count` is then recomputed.

Each discrepancy carries its parent `work_order_id`, a `checklist_item_id` linking back to the checklist line that surfaced it, a `description` of the finding, a `severity` of `AIRWORTHINESS` (grounding) or `NON_AIRWORTHINESS` (deferrable), and the shop's `estimated_cost_cents` to rectify. The completion cascade is the only creation path the API exposes — no endpoint registers a discrepancy directly — so in practice every discrepancy links a checklist item and carries the cascade's `AIRWORTHINESS` severity and 50,000-cent estimate; a squawk discovered outside the checklist (null `checklist_item_id`) and the `NON_AIRWORTHINESS` value remain model possibilities that no API path produces. Its `status` walks a seven-state machine: `OPEN`, `PENDING_OWNER_DECISION`, `APPROVED`, `DEFERRED`, `REJECTED`, `RECTIFIED`, and `VERIFIED`, beginning at `OPEN` and ending at `VERIFIED`, `REJECTED`, or `DEFERRED`. The work order's `open_discrepancy_count` counts child discrepancies in `OPEN`, `PENDING_OWNER_DECISION`, `APPROVED`, or `RECTIFIED` — verified, rejected, and deferred findings no longer count as open — while `verified_discrepancy_count` counts those that have reached `VERIFIED`.

### 3.4. Airworthiness Directives and Service Bulletins

Compliance with directives is tracked per aircraft, independent of any single work order. A `ShopManager` registers a directive against an `aircraft_id` with a `directive_type` — `AD` for a mandatory Airworthiness Directive or `SB` for an advisory Service Bulletin — a `reference_number` such as AD 2023-14-08, and a `description` of the subject. A new directive's `compliance_status` is `PENDING_EVALUATION`, which does not by itself affect the aircraft's posture.

Applicability is determined by a `Mechanic`, who evaluates the directive by setting its `compliance_status` to `APPLICABLE_OPEN`, `COMPLIED`, or `NOT_APPLICABLE`; the system records the evaluator in `evaluated_by_mechanic_id`. Evaluation is permitted from any current `compliance_status`, including re-evaluation of an already-evaluated directive. Evaluation is a posture-relevant event: an `AD` found `APPLICABLE_OPEN` grounds the aircraft immediately through the posture derivation described in §3.7, while service bulletins, being advisory, never ground. Directives are listable per aircraft or shop-wide, filtered by `compliance_status` or `evaluated_by_mechanic_id`, and the regulatory gate at return to service requires every applicable AD to be closed out, as §3.7 describes.

### 3.5. The Owner Approval Gate

Once the inspection is complete and findings exist, the shop takes the discrepancy list to the owner. Submitting the work order for approval moves it from `INSPECTION_COMPLETE` to `AWAITING_OWNER_APPROVAL` and is permitted only when `open_discrepancy_count` is greater than zero and at least one discrepancy remains `OPEN` or `PENDING_OWNER_DECISION`; a submission failing either condition is rejected with `ERR_INVALID_STATE` (HTTP 409). Submission is the moment the owner's `approval_cap_cents` bites: for each `OPEN` discrepancy the system computes `requires_owner_decision` by comparing the `estimated_cost_cents` against the cap of the aircraft's owner at that instant. Every `OPEN` discrepancy whose estimate is at or above the cap — `requires_owner_decision` true — moves to `PENDING_OWNER_DECISION`; every `OPEN` discrepancy under the cap auto-transitions straight to `APPROVED`, the under-cap auto-approval that keeps small findings from clogging the owner's queue. This cap gate is absolute: an at-or-above-cap finding can never be auto-approved, a rule catalogued as `ERR_OWNER_DECISION_REQUIRED` (HTTP 422).

The owner then dispositions each pending finding. A decision call carries a `decision` of `APPROVE`, `REJECT`, or `DEFER` and — per §2.6 — an `expected_discrepancy_version` matching the discrepancy's current `version`, with a stale read rejected by `ERR_STALE_VERSION`. Within the call, checks fire in a pinned order: the version check, then state permissibility (the discrepancy must stand `PENDING_OWNER_DECISION`, else `ERR_INVALID_STATE`), then registered-owner identity, then the severity gate. Only the aircraft's registered owner may decide; a decision attempted by anyone else is rejected with `ERR_OWNER_DECISION_REQUIRED`. An approval moves the discrepancy to `APPROVED`. Rejection and deferral move it to `REJECTED` or `DEFERRED` respectively, but both are reserved for `NON_AIRWORTHINESS` findings — an airworthiness finding may never be rejected or deferred away, and attempting either on one is rejected with `ERR_AIRWORTHINESS_BLOCKED` (HTTP 422). Whichever the outcome, the system stamps `decided_by_owner_id` with the deciding owner's `id`, recomputes the work order's open count, and watches for completion: the instant no discrepancy remains in `OPEN` or `PENDING_OWNER_DECISION`, the work order auto-advances from `AWAITING_OWNER_APPROVAL` to `APPROVED` with no separate client call.

An owner who wants a second look before deciding may instead send the work order back: reopening the inspection moves it from `AWAITING_OWNER_APPROVAL` to `IN_PROGRESS`, and every `PENDING_OWNER_DECISION` discrepancy reverts to `OPEN` for re-inspection. Only the aircraft's registered owner may request the reopen; anyone else is rejected with `ERR_OWNER_DECISION_REQUIRED` (HTTP 422). Once the order stands `APPROVED` — with nothing left `OPEN` or `PENDING_OWNER_DECISION`, and either at least one discrepancy `APPROVED` or all findings already `RECTIFIED` or `VERIFIED` — a `Mechanic` begins repair work, moving the order to `WORK_IN_PROGRESS`. Begin-work re-checks these conditions and rejects violations with `ERR_INVALID_STATE` (HTTP 409); an order with no discrepancies at all satisfies neither branch and cannot begin work.

### 3.6. Executing Repairs: Labor, Parts, and Independent Verification

Repair work produces two kinds of records. The first is labor. A `Mechanic` posts a labor entry naming the `mechanic_id` who performed the work, a `duration_tenths` measured in tenths of an hour, and free-text `notes`. The billable increment is pinned: `duration_tenths` must be positive and a whole multiple of three — three tenths of an hour, eighteen minutes, is the smallest billable unit — and anything else is rejected with `ERR_VALIDATION`. Labor may be posted in any work-order state except `CLOSED` and `CANCELLED`, where it is rejected with `ERR_INVALID_STATE` (HTTP 409). An entry is `POSTED` when created (the model also defines a `VOIDED` status, but no API operation voids a labor entry); the work order's `labor_hours_tenths` accumulates the `duration_tenths` of its non-voided entries only. The shop also protects its mechanics from impossible days: a labor posting is rejected with `ERR_MECHANIC_OVERBOOKED` (HTTP 409) whenever the mechanic's same-day `POSTED` entries — same-day being measured on the logical clock's UTC calendar date — already total enough that adding the new `duration_tenths` would exceed 100 tenths (ten billable hours); a day total of exactly 100 tenths remains permitted.

The second kind of record is parts. A `Mechanic` or `PartsClerk` requests a part against a `discrepancy_id` with the manufacturer `part_number`, the `condition` — `NEW`, `OVERHAUL`, or `SERVICEABLE` — the `unit_cost_cents`, and a `quantity` of at least one. A `serial_number` may be supplied with any `condition` and may be left empty for any `condition` — the API enforces no serial-number requirement. The `trace_doc_ref` — the 8130-3, yellow-tag, or invoice reference — is optional at request time but becomes mandatory downstream for `OVERHAUL` and `SERVICEABLE` parts. A requested part walks the sourcing pipeline: a `PartsClerk` marks it `SOURCED`, which is the first traceability checkpoint — an `OVERHAUL` or `SERVICEABLE` part lacking a non-empty `trace_doc_ref` at this point is rejected with `ERR_TRACEABILITY_MISSING` (HTTP 422). The clerk then receives it, moving `SOURCED` to `RECEIVED`. From there a part either goes in or goes back: a `Mechanic` installs it, moving `RECEIVED` to `INSTALLED`, which requires the parent discrepancy to stand `APPROVED` — a parent in any other status fails with `ERR_INVALID_STATE` (HTTP 409) — and re-checks traceability for `OVERHAUL` and `SERVICEABLE` parts, again failing with `ERR_TRACEABILITY_MISSING` when the document reference is empty; or a `PartsClerk` returns it, moving `RECEIVED` to `RETURNED`, appropriate when the parent discrepancy was `REJECTED` or `DEFERRED` or the part is simply no longer required. Installation re-evaluates the parent discrepancy's progress: when every part on an approved discrepancy is installed, the finding becomes eligible for rectification.

Rectification is the mechanic's claim that the approved fix is done, moving the discrepancy from `APPROVED` to `RECTIFIED`. The claim is gated: every part linked to the discrepancy that was not returned must stand `INSTALLED`, and there must be at least one installed part — unless the discrepancy genuinely required no parts at all, meaning no part records reference it (a discrepancy whose parts were all returned cannot be rectified); either failure is rejected with `ERR_INVALID_STATE` (HTTP 409). The acting request's `X-User-ID` is recorded as the rectifying mechanic for the segregation-of-duties check. Verification is the independent check that closes the loop. A `Mechanic` verifies a rectified discrepancy by submitting an `outcome` and a `verified_by_mechanic_id`. Segregation of duties is enforced: the verifying mechanic's `id` must differ from the rectifying mechanic's `id`, and a violation is rejected with `ERR_AIRWORTHINESS_BLOCKED` (HTTP 422); on an `ANNUAL`-scope work order the verifier must additionally hold an `IA` certificate. Both checks apply only to a passing outcome; a failing outcome reopens the discrepancy unconditionally, with no segregation or certificate check. A passing outcome moves the discrepancy to `VERIFIED`, decrementing the work order's `open_discrepancy_count` and incrementing its `verified_discrepancy_count`. A failing outcome reopens the discrepancy to `OPEN` and begins a rework cycle — the aircraft's posture is recomputed at that point and may regress to `RESTRICTED` or `GROUNDED`.

### 3.7. Return to Service, Logbooks, and the Airworthiness Posture

The aircraft's `airworthiness_posture` is derived continuously from the fleet-wide compliance picture, recomputed whenever any discrepancy status, any directive's `compliance_status`, or any work-order status for that aircraft changes. The derivation considers directives registered to the aircraft and discrepancies across all of the aircraft's non-cancelled work orders. The aircraft is `GROUNDED` whenever at least one `AD` directive stands `APPLICABLE_OPEN`, or at least one `AIRWORTHINESS`-severity discrepancy stands `OPEN`, `PENDING_OWNER_DECISION`, `APPROVED`, or `RECTIFIED`. Failing that, it is `RESTRICTED` whenever any discrepancy of either severity stands in one of those four non-terminal statuses. Otherwise the aircraft is `AIRWORTHY`. The `posture_reason` field records which rule produced the current value, rendered as `GROUNDED: N AD directive(s) APPLICABLE_OPEN` when open ADs ground the aircraft (this rule is reported first when several apply), `GROUNDED: N open airworthiness discrepancy(ies)` for open grounding findings, `RESTRICTED: N open discrepancy(ies)`, or `AIRWORTHY: no open ADs or discrepancies`.

Three gates stand between finished work and a legal flight. Declaring readiness moves the work order from `WORK_IN_PROGRESS` to `READY_FOR_RTS` and demands a clean sheet: `open_discrepancy_count` must be zero with every discrepancy `VERIFIED`, `DEFERRED`, or `REJECTED`; every `AIRWORTHINESS`-severity discrepancy must be `VERIFIED` with none deferred or rejected; and every `AD` directive on the aircraft must stand `COMPLIED` or `NOT_APPLICABLE`. A failure of this regulatory gate is `ERR_AIRWORTHINESS_BLOCKED`, and the aircraft's posture is recomputed on success.

The logbook is the legal memory of the work. A `Mechanic` appends entries — the logbook is append-only and immutable — supplying the `aircraft_id`, the `work_order_id` the entry closes out, an `entry_type` of `INSPECTION_SIGNOFF`, `REPAIR_RECORD`, or `RTS_STATEMENT`, the `narrative` text per 14 CFR 43.11, and the `signed_by_mechanic_id`. The named work order must belong to the named aircraft — a mismatch is rejected with `ERR_VALIDATION` (HTTP 400) — and appending is not gated on the work order's status. The server stamps `signed_at` from the logical clock. For `ANNUAL`-scope work the signatory must hold an `IA` certificate; the regulatory gate rejects an insufficient signatory with `ERR_AIRWORTHINESS_BLOCKED`.

Return to service moves the order from `READY_FOR_RTS` to `RETURNED_TO_SERVICE` and is the most heavily guarded transition in the system. The returning mechanic must hold an `IA` certificate when the scope is `ANNUAL` — an `AP` certificate suffices otherwise, and a certificate shortfall is rejected with `ERR_CERTIFICATE_INSUFFICIENT` (HTTP 422). The aircraft's `airworthiness_posture` must stand `AIRWORTHY`. And an `RTS_STATEMENT` logbook entry must already exist for the work order — the paperwork precedes the airplane. Taken together, the regulatory airworthiness gate `ERR_AIRWORTHINESS_BLOCKED` guards four operations: declaring readiness, returning to service, verifying a rectified discrepancy, and appending a logbook entry. On a successful return, three cascades fire: the hangar slot moves to `RELEASED` and its occupancy is freed; a `DRAFT` invoice is auto-created with every computed line populated, as §3.8 details; and the invoice's `warranty_expires_at` is set to the return-to-service instant plus ninety days, opening the shop's maintenance warranty window.

### 3.8. Invoicing, Settlement, and Warranty

Each work order produces at most one active invoice — the `work_order_id` on an invoice is unique per work order among non-`VOIDED` rows — and the invoice is born `DRAFT` at the moment of return to service with all computed fields populated. That return-to-service cascade is the only invoice-creation path: the API exposes no invoice-generation endpoint, the cascade suppresses creation if a non-`VOIDED` invoice somehow already exists, and the catalogued `ERR_DUPLICATE_INVOICE` (HTTP 409) therefore has no client-reachable trigger. The invoice's lines are computed in a pinned order that breaks the circularity between the supplies surcharge and the tax base: parts first, then supplies, then labor, then hangar, then tax, then the total.

`parts_charge_cents` sums every `INSTALLED` part on the work order's discrepancies — parts still `REQUESTED`, `SOURCED`, `RECEIVED`, or `RETURNED` are excluded — multiplying each line's `quantity` by its `unit_cost_cents`, rounding each line half up to whole cents, and summing the rounded lines. `shop_supplies_cents` is tiered on that rounded parts total: five percent when the parts total is below 50,000 cents, eight percent when it is 50,000 cents or more, with the fee itself rounded half up to whole cents. `labor_charge_cents` depends on the work order's `pricing_mode`. Under `HOURLY`, each `POSTED` labor entry is priced individually: its `duration_tenths` divided by ten yields hours, multiplied by the performing mechanic's `hourly_rate_cents`, rounded half up to whole cents per entry, and the rounded entries are summed. Under `FLAT_RATE`, labor entries are still recorded for the record but never billed; instead the charge is the sum of `flat_rate_cents` over checklist items whose `result` is `PASS` or `FAIL`, with `NA` items excluded. `hangar_fee_cents` bills the slot by calendar day: the number of billing days runs from the UTC calendar date of `starts_at` through the UTC calendar date of `ends_at` inclusive — so a twenty-five-hour slot that crosses one UTC midnight bills two days, a one-hour slot bills a single day, and a slot whose `ends_at` falls exactly on a UTC midnight bills that midnight's date as an additional day — multiplied by the slot's `daily_rate_cents`. `tax_cents` is 8.25 percent of the sum of labor, parts, and shop supplies — the hangar fee is tax-exempt — rounded half up to whole cents. Finally `total_cents` is the sum of labor, parts, supplies, hangar fee, and tax.

Settlement walks a short lifecycle. A `ShopManager` issues a `DRAFT` invoice, moving it to `ISSUED`, which requires the work order to stand `RETURNED_TO_SERVICE`; issuance attempted when either condition fails is rejected with `ERR_INVALID_STATE` (HTTP 409). The aircraft's registered owner pays, moving `ISSUED` to `PAID`; a payment attempted by anyone else is rejected with `ERR_OWNER_DECISION_REQUIRED` (HTTP 422). A `ShopManager` may instead void a `DRAFT` invoice when it was generated in error, moving it to `VOIDED`; the `VOIDED` row is retained and remains visible in the work order's invoice listing, and — return to service being a one-time transition — no further invoice is generated for the work order. Issuance is the point of fiscal no-return: once an invoice stands `ISSUED` or `PAID`, the underlying work order is locked — no further labor entries may be posted, no parts may be installed, and no discrepancies may be rectified — and any such attempt is rejected with `ERR_INVOICE_LOCKED` (HTTP 409).

Only then can the file be closed: a `ShopManager` closes a `RETURNED_TO_SERVICE` work order, moving it to `CLOSED`, permitted only when its invoice stands `PAID` or `VOIDED`; otherwise the close is rejected with `ERR_INVALID_STATE` (HTTP 409). The ninety-day warranty recorded in `warranty_expires_at` survives closure as the shop's commitment to the work.

## 4. Endpoint Definitions

Endpoints that create a new resource — registering an owner, aircraft, mechanic, or part, reserving a hangar slot, opening a work order, adding a checklist item, posting a labor entry, registering a directive, or appending a logbook entry — return `201 Created`. Endpoints that modify an existing resource, including every state-transition action, return `200 OK`; the logical-clock capability likewise returns `200 OK`. The table below is a navigational summary only: request payloads, derived fields, and side effects are defined by the narratives in §2 and §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/api/owners` | Register an owner | ShopManager |
| GET | `/api/owners` | List owners | ShopManager |
| GET | `/api/owners/{id}` | Get an owner | ShopManager, Owner |
| GET | `/api/owners/{id}/aircraft` | List aircraft registered to an owner | ShopManager, Owner |
| POST | `/api/aircraft` | Register an aircraft | ShopManager |
| GET | `/api/aircraft` | List aircraft | ShopManager, Mechanic, Owner, PartsClerk |
| GET | `/api/aircraft/{id}` | Get an aircraft with its derived posture | ShopManager, Mechanic, Owner, PartsClerk |
| GET | `/api/aircraft/{id}/directives` | List directives for an aircraft | ShopManager, Mechanic, Owner |
| GET | `/api/aircraft/{id}/logbook-entries` | List an aircraft's logbook entries (append-only) | ShopManager, Mechanic, Owner |
| POST | `/api/mechanics` | Register a mechanic | ShopManager |
| GET | `/api/mechanics` | List mechanics | ShopManager, PartsClerk |
| GET | `/api/mechanics/{id}` | Get a mechanic | ShopManager |
| POST | `/api/hangar-slots` | Reserve a hangar slot (half-open overlap enforced) | ShopManager |
| GET | `/api/hangar-slots` | List hangar slots | ShopManager, Mechanic |
| GET | `/api/hangar-slots/{id}` | Get a hangar slot | ShopManager, Mechanic |
| POST | `/api/work-orders` | Open a work order (OCC on the hangar slot's version) | ShopManager |
| GET | `/api/work-orders` | List work orders | ShopManager, Mechanic, Owner, PartsClerk |
| GET | `/api/work-orders/{id}` | Get a work order | ShopManager, Mechanic, Owner, PartsClerk |
| POST | `/api/work-orders/{id}/schedule` | Schedule a work order (`DRAFT` → `SCHEDULED`) | ShopManager |
| POST | `/api/work-orders/{id}/start` | Start work (`SCHEDULED` → `IN_PROGRESS`); occupies the slot | Mechanic |
| POST | `/api/work-orders/{id}/checklist-items` | Add a checklist item | Mechanic |
| GET | `/api/work-orders/{id}/checklist-items` | List a work order's checklist items | ShopManager, Mechanic, Owner |
| GET | `/api/checklist-items/{id}` | Get a checklist item by id | ShopManager, Mechanic, Owner |
| GET | `/api/checklist-items` | List checklist items shop-wide (filtered) | ShopManager, Mechanic, Owner |
| POST | `/api/work-orders/{id}/checklist-items/{item_id}/record` | Record `PASS` / `FAIL` / `NA` on a checklist item | Mechanic |
| POST | `/api/work-orders/{id}/complete-inspection` | Complete the inspection (`IN_PROGRESS` → `INSPECTION_COMPLETE`) | Mechanic |
| POST | `/api/work-orders/{id}/submit-for-approval` | Submit findings for owner approval (`INSPECTION_COMPLETE` → `AWAITING_OWNER_APPROVAL`) | Mechanic |
| POST | `/api/work-orders/{id}/reopen-inspection` | Reopen the inspection at the owner's request (`AWAITING_OWNER_APPROVAL` → `IN_PROGRESS`) | Owner |
| POST | `/api/work-orders/{id}/begin-work` | Begin repairs (`APPROVED` → `WORK_IN_PROGRESS`) | Mechanic |
| POST | `/api/work-orders/{id}/labor-entries` | Post a labor entry in tenths of an hour | Mechanic |
| GET | `/api/work-orders/{id}/labor-entries` | List a work order's labor entries | ShopManager, Mechanic, Owner |
| GET | `/api/labor-entries/{id}` | Get a labor entry by id | ShopManager, Mechanic, Owner |
| GET | `/api/labor-entries` | List labor entries shop-wide (filtered) | ShopManager, Mechanic, Owner |
| POST | `/api/work-orders/{id}/ready-for-rts` | Declare readiness (`WORK_IN_PROGRESS` → `READY_FOR_RTS`) | Mechanic |
| POST | `/api/work-orders/{id}/return-to-service` | Return the aircraft to service; auto-creates the `DRAFT` invoice | Mechanic |
| POST | `/api/work-orders/{id}/close` | Close a returned work order (`RETURNED_TO_SERVICE` → `CLOSED`) | ShopManager |
| POST | `/api/work-orders/{id}/cancel` | Cancel a draft work order (`DRAFT` → `CANCELLED`) | ShopManager |
| GET | `/api/work-orders/{id}/discrepancies` | List a work order's discrepancies | ShopManager, Mechanic, Owner |
| GET | `/api/work-orders/{id}/invoice` | List the work order's invoices as a paginated array (all rows, including `VOIDED`) | ShopManager, Owner |
| GET | `/api/discrepancies/{id}` | Get a discrepancy by id | ShopManager, Mechanic, Owner |
| GET | `/api/discrepancies` | List discrepancies shop-wide (filtered) | ShopManager, Mechanic, Owner |
| POST | `/api/discrepancies/{id}/decide` | Record the owner's `APPROVE` / `REJECT` / `DEFER` decision (OCC on the discrepancy's version) | Owner |
| POST | `/api/discrepancies/{id}/rectify` | Mark an approved discrepancy rectified (`APPROVED` → `RECTIFIED`) | Mechanic |
| POST | `/api/discrepancies/{id}/verify` | Verify rectification — `PASS` moves to `VERIFIED`, `FAIL` reopens to `OPEN`; segregation of duties enforced | Mechanic |
| POST | `/api/directives` | Register an AD or SB against an aircraft | ShopManager |
| POST | `/api/directives/{id}/evaluate` | Set a directive's compliance status | Mechanic |
| GET | `/api/directives` | List directives (filtered) | ShopManager, Mechanic, Owner |
| GET | `/api/directives/{id}` | Get a directive by id | ShopManager, Mechanic, Owner |
| POST | `/api/parts` | Request a part for a discrepancy | Mechanic, PartsClerk |
| GET | `/api/parts` | List parts (filtered) | ShopManager, Mechanic, PartsClerk |
| GET | `/api/parts/{id}` | Get a part by id | ShopManager, Mechanic, PartsClerk |
| POST | `/api/parts/{id}/mark-sourced` | Mark a part sourced (`REQUESTED` → `SOURCED`) | PartsClerk |
| POST | `/api/parts/{id}/receive` | Receive a sourced part (`SOURCED` → `RECEIVED`) | PartsClerk |
| POST | `/api/parts/{id}/install` | Install a received part (`RECEIVED` → `INSTALLED`); gates on the parent discrepancy | Mechanic |
| POST | `/api/parts/{id}/return` | Return a received part (`RECEIVED` → `RETURNED`) | PartsClerk |
| POST | `/api/logbook-entries` | Append an immutable logbook entry | Mechanic |
| GET | `/api/logbook-entries` | List logbook entries (filtered) | ShopManager, Mechanic, Owner |
| GET | `/api/logbook-entries/{id}` | Get a logbook entry by id | ShopManager, Mechanic, Owner |
| POST | `/api/invoices/{id}/issue` | Issue a draft invoice (`DRAFT` → `ISSUED`) | ShopManager |
| POST | `/api/invoices/{id}/pay` | Pay an issued invoice (`ISSUED` → `PAID`) | Owner |
| POST | `/api/invoices/{id}/void` | Void a draft invoice (`DRAFT` → `VOIDED`) | ShopManager |
| GET | `/api/invoices/{id}` | Get an invoice | ShopManager, Owner |
| POST | `/api/_clock/set_current_utc` | Advance the shop's logical clock | ShopManager |

## 5. Error Code Catalogue

The catalogue below enumerates every error identifier and its HTTP status. Trigger conditions are specified in the narratives of §2 and §3 rather than in this table; the single exception is `ERR_INTERNAL`, the fallback for unexpected server faults, which no domain narrative triggers.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_SLOT_OVERLAP` | 409 |
| `ERR_INVALID_WINDOW` | 422 |
| `ERR_MECHANIC_OVERBOOKED` | 409 |
| `ERR_TRACEABILITY_MISSING` | 422 |
| `ERR_AIRWORTHINESS_BLOCKED` | 422 |
| `ERR_OWNER_DECISION_REQUIRED` | 422 |
| `ERR_INVOICE_LOCKED` | 409 |
| `ERR_VALIDATION` | 400 |
| `ERR_CHECKLIST_INCOMPLETE` | 422 |
| `ERR_DUPLICATE_INVOICE` | 409 |
| `ERR_CERTIFICATE_INSUFFICIENT` | 422 |
| `ERR_INTERNAL` | 500 |
