# Custom-Exempt Locker API — Product Requirements Document

## 1. Introduction

A custom-exempt locker plant occupies a particular niche in the meat trade: it slaughters, fabricates, and wraps livestock exclusively for the animal's owner and declared co-owners, and every package leaving the building is marked not for resale. Because the product never enters inspected commerce, the plant's regulatory burden concentrates on truthful labeling and on a clean chain of identity from the live animal at the unloading chute to the boxed share in the freezer. Operationally the business is seasonal and capacity-bound — slaughter dates are booked far in advance against a per-day head limit, deposits protect the calendar slot, and freezer space is small enough that unclaimed boxes become a genuine financial exposure.

This document specifies the Custom-Exempt Locker API, which governs that entire lifecycle: opening slaughter capacity days, booking deposit-backed appointments, receiving and identifying animals at drop-off, recording slaughter and hanging weight, splitting carcass ownership among multiple buyers, capturing per-share cutting instructions, billing on hanging weight with tiered processing rates, accruing freezer storage, enforcing the custom-exempt labeling gate before pickup, and applying the no-show and abandoned-meat policies that protect the plant from calendar and freezer abuse. All deadlines, windows, and sweeps in the system evaluate against a controllable logical clock so that the full timeline — from a booking made weeks ahead to an abandonment sweep three weeks after ready — is deterministically testable.

## 2. Global Specifications & System-Wide Principles

This section defines the contract-level rules that apply uniformly across the API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. The system recognizes exactly three roles, spelled as follows: `Customer`, `PlantOperator`, and `PlantManager`. A request missing either header, or presenting a role outside this enumeration, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is not permitted on the targeted endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403).

Role identity works differently per role. When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting Customer; ownership checks on any resource that references a Customer compare the resource's foreign-key field to `X-User-ID`. Concretely, a Customer caller owns an appointment when its `customer_id` equals `X-User-ID`, owns a carcass share when its `owner_customer_id` equals `X-User-ID`, and owns invoices, storage records, label records, and cut sheets through the share those resources reference. List endpoints reflect the same rule: a Customer sees only their own appointments, only shares they own, and only invoices, storage records, label records, and cut sheets attached to those shares. When `X-User-Role` is `PlantOperator` or `PlantManager`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server never compares it to any entity's `id`. The `PlantManager` role is a strict superset of `PlantOperator`: everything an operator can do, plus capacity planning, storage-fee waivers, and control of the logical clock.

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

List endpoints accept two query parameters. The `limit` parameter caps the number of items returned: it defaults to 10 when omitted, accepts a minimum of 1, and rejects values above 100. The `offset` parameter skips a number of items from the front of the result set and defaults to 0. All list endpoints sort by `created_at` in ascending order. The `meta` object of every list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. The Logical Clock

The system runs on a logical clock rather than the wall clock. At server startup the logical clock reads exactly `2026-08-01T00:00:00Z`, and until it is explicitly set it never consults the wall clock. A manager-only test-driving capability, `POST /_clock/set_current_utc`, advances the logical clock to a supplied `to_iso8601` instant and responds with the new logical time as `current_utc`. Every deadline, window, day count, sweep decision, and system-stamped record timestamp — `created_at`, `received_at`, `slaughtered_at`, `weighed_at`, `ready_at`, `picked_up_at`, `deposit_due_at` — evaluates against this logical time. Day counts throughout this document are whole calendar days measured on logical-clock date boundaries.

### 2.5. Common Resource Properties

Every resource in the system — Customer, CapacityDay, Appointment, Animal, CarcassShare, CutSheet, Invoice, StorageRecord, and LabelRecord — carries the same four system-managed fields:

- `id` — a server-minted UUID string with no type prefix.
- `created_at` — an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` — an ISO 8601 UTC timestamp refreshed on every mutation of the resource.
- `version` — an integer that starts at creation and increments by exactly 1 on every mutation, including system-driven cascades and bubble-ups.

### 2.6. Money, Weights, and Rounding Discipline

All monetary amounts are represented as integer cents; there are no fractional-cent values anywhere in the system. Whenever a calculation produces a fractional cent, the result is rounded half-up to a whole cent. Weights — live, hanging, estimated, and allocated — are recorded in pounds to exactly one decimal place, and weight calculations round half-up to that single decimal. Day-based quantities (lead time, hang time, storage duration, cancellation windows) are whole days on the logical clock as described in §2.4. These conventions apply to every formula in §3 without exception.

### 2.7. Optimistic Concurrency Control

Two write operations require the caller to prove it has observed the current state of the resource it is modifying. Rescheduling an appointment requires the request to carry `expected_appointment_version` holding the appointment's current `version` as last observed by the client; because rescheduling is a self-loop that leaves the appointment's status unchanged, staleness cannot be detected from status alone, and a request whose value does not match the appointment's current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412). Revising a cut sheet likewise requires `expected_cut_sheet_version` matching the cut sheet's current `version` — revision is legitimate from both of its non-terminal states, so a stale client would otherwise silently overwrite newer instructions — and a mismatch is rejected with the same `ERR_STALE_VERSION` (HTTP 412). No other endpoint accepts or requires a version field.

### 2.8. Existence Checking and Validation Order

Nested resources are addressed by path identifiers, and every `id` appearing in a request path is validated for existence in strict left-to-right order; the first identifier that does not correspond to an existing resource yields `ERR_NOT_FOUND` (HTTP 404). Foreign-key references supplied in request bodies — `customer_id`, `capacity_day_id`, `new_capacity_day_id`, `owner_customer_id` — must likewise reference existing resources or the request fails with `ERR_NOT_FOUND`. At the same tier, the request body itself must be well-formed: required fields present, enum members drawn from the declared sets, numeric domains respected (`capacity_head` and `head_count` at least 1, `share_fraction` greater than 0 and at most 1.0 with no more than three decimal places, `package_weight_lbs` at least 1.0, `grind_pct` between 0 and 100, `steak_thickness_in` between 0.5 and 2.0 inches when supplied, `amount_cents` at least 1), capacity-day dates unique across all CapacityDay rows, and no undeclared fields. Any well-formedness failure is `ERR_INVALID_REQUEST` (HTTP 400).

When several checks could reject the same request, the server evaluates them in a fixed order so the reported error is deterministic: authentication first (`ERR_UNAUTHENTICATED`), then authorization and entity-backed ownership (`ERR_FORBIDDEN`), then existence and body well-formedness (`ERR_NOT_FOUND`, `ERR_INVALID_REQUEST`), then state-transition legality including terminal-state lockdown (`ERR_INVALID_STATE`, HTTP 409) together with stale-version rejection (`ERR_STALE_VERSION`), then the custom-exempt resale-label safety rule (`ERR_RESALE_LABEL_FORBIDDEN`), then the business constraints such as blocked customers, capacity, split allocation, tag uniqueness, yield feasibility, and freezer room, then the temporal window rules (lead time, minimum hang, premature no-show), then referential completeness (missing cut sheets, unapproved labels), and finally the fiscal checks (`ERR_OUTSTANDING_BALANCE`, `ERR_DEPOSIT_INSUFFICIENT`, `ERR_INVOICE_NOT_PAID`). Consequently, a fabrication start attempted both before the minimum hang has elapsed and while a confirmed share still lacks submitted instructions reports `ERR_MIN_HANG_NOT_MET`, and a pickup attempted with an unapproved label and an unpaid invoice reports `ERR_LABEL_NOT_APPROVED` rather than the fiscal error.

### 2.9. Cascades, Bubble-Ups, and Version Discipline

The hierarchy reconciles itself without client intervention. When an appointment is cancelled or marked as a no-show, its still-expected animals are voided and each voided animal releases one head of capacity back to its day. When the last expected animal of an appointment is received at drop-off, the appointment bubbles up from `CONFIRMED` to `COMPLETED`. When fabrication completes, the animal's confirmed shares become ready and each acquires a freezer storage record. When a share reaches a terminal state — picked up or forfeited — and every sibling share is also terminal, the animal bubbles up from `READY` to `COMPLETE`. Forfeiture cascades further: the share's invoice is driven into collections with a surcharge, and the strike is charged to the owning customer. Each such automatic mutation independently refreshes `updated_at` and increments `version` on whatever entity it touches, exactly as a client-driven mutation would.

### 2.10. The Custom-Exempt Labeling Regime

This plant performs custom-exempt slaughter only. Every label record carries `program` fixed to `CUSTOM_EXEMPT`; inspected or retail labeling is never issued, and no product may bear an inspection legend. The computed `label_text` always begins with the exact string `NOT FOR SALE`, followed by the owner name and a description of the share. Because custom-exempt product may not be resold, a share whose declared end use is resale can never pass label approval — that refusal is a hard compliance gate standing between the freezer and the customer, described in §3.7.

## 3. Business Logic & Workflows

### 3.1. Capacity Planning, Customer Registration, and Booking

The planning cycle begins when a `PlantManager` opens a slaughter capacity day by supplying a `date` — an ISO 8601 calendar date that must be unique across all capacity days, with a duplicate rejected as `ERR_INVALID_REQUEST` — and a `capacity_head` of at least one animal. A freshly opened day has `booked_head` of zero and status `OPEN`; the day flips to `FULL` exactly when `booked_head` reaches `capacity_head` and returns to `OPEN` the moment a cancellation, expiry, or no-show releases headroom. Customers may browse the calendar themselves: the capacity-day listing accepts optional `date_from`, `date_to`, and `status` filters alongside the standard pagination parameters, so a rancher planning the fall kill can scan which days remain `OPEN`.

Front-desk staff register customers with a `name`, `phone`, and `email`. A new customer starts with `no_show_strikes` at zero and standing `ACTIVE`. Standing is derived entirely from strikes: zero strikes yields `ACTIVE`, one strike yields `ELEVATED_DEPOSIT`, and two or more strikes yields `BLOCKED`. Staff can list customers and filter by `status`.

Booking an appointment requires a payload naming the booking party via `customer_id`, the reserved day via `capacity_day_id`, the `species` — one of `BEEF`, `HOG`, `LAMB`, or `GOAT` — and a `head_count` of at least one. A `Customer` caller may only book for themselves, meaning the `customer_id` must equal their `X-User-ID`; `PlantOperator` and `PlantManager` callers may book on behalf of any registered customer. Several guards stand in front of a successful booking, and per the evaluation order of §2.8 the standing and capacity checks fire ahead of the temporal and fiscal gates: a customer whose standing is `BLOCKED` is turned away with `ERR_CUSTOMER_BLOCKED`; if the day's `booked_head` plus the requested `head_count` would exceed `capacity_head` — where `booked_head` aggregates all appointments on that day still in `PENDING_DEPOSIT` or `CONFIRMED` — the request fails with `ERR_CAPACITY_FULL`; the reserved date must fall at least fourteen days after the current date, with a date exactly fourteen days out acceptable, otherwise `ERR_LEAD_TIME_TOO_SHORT`; and a customer with any invoice sitting in `COLLECTIONS` must settle that abandoned-meat debt before booking again, else `ERR_OUTSTANDING_BALANCE`.

Before the appointment is persisted, the server quotes its deposit, and the quoted variant depends on the customer's standing at booking time. For an `ACTIVE` customer the quote is a flat per-head rate by species multiplied by the head count: 15000 cents per head for `BEEF`, 7500 for `HOG`, and 5000 for either `LAMB` or `GOAT`. For a customer carrying a strike — standing `ELEVATED_DEPOSIT` — the quote instead estimates the value of the work to be performed: the plant's reference live weight for the species (1200 pounds for `BEEF`, 280 for `HOG`, 130 for `LAMB`, 90 for `GOAT`) is multiplied by the species dressing percentage (0.62 for `BEEF`, 0.75 for `HOG`, 0.52 for `LAMB`, 0.50 for `GOAT`) and by the head count to obtain an estimated hanging weight; that weight is priced through the same two-tier processing schedule used at invoice settlement (§3.6); the species slaughter fee — 12000 cents for `BEEF`, 6000 for `HOG`, 4500 for `LAMB` and `GOAT` — multiplied by the head count is added; and the deposit is one half of the resulting estimated value, rounded half-up to a whole cent. A `BLOCKED` customer never reaches this calculation, because the booking is refused first. For an identical species and head count the two variants produce different numbers — a single-head beef booking, for instance, quotes 15000 cents flat for a clean customer but a materially higher half-value figure for a customer with a strike.

A successfully created appointment lands in `PENDING_DEPOSIT` with `deposit_amount_cents` set to the quote, `deposit_paid_cents` at zero, `refund_cents` at zero, `appointment_date` copied from the reserved day, and `deposit_due_at` exactly 48 hours after the appointment's `created_at`. The day's `booked_head` immediately increases by `head_count`, which may flip the day to `FULL`. Appointments can be listed with optional `customer_id`, `capacity_day_id`, and `status` filters; customers listing their own history see only appointments where they are the booking party.

### 3.2. Deposits, Rescheduling, Cancellation, and Expiry

A booking is only held for 48 hours unpaid. Paying the deposit is the booking customer's own action: the payment must be at least the remaining deposit due — `deposit_amount_cents` minus whatever `deposit_paid_cents` has already accumulated — or it is refused with `ERR_DEPOSIT_INSUFFICIENT`. A successful payment adds the paid amount to `deposit_paid_cents`, moves the appointment from `PENDING_DEPOSIT` to `CONFIRMED`, and creates one Animal row per booked head, each in `EXPECTED` status with its `species` copied from the appointment and its `appointment_id` pointing back to the booking.

Plans change, and a customer may move their booking to a different day. Rescheduling is a self-loop available from both `PENDING_DEPOSIT` and `CONFIRMED`: the appointment's status does not change, only its calendar placement. The request names the target day via `new_capacity_day_id` and must carry `expected_appointment_version` per §2.7. The target day must exist, its date must satisfy the same fourteen-day lead rule, and it must have room for the booking's `head_count`; the same `ERR_NOT_FOUND`, `ERR_LEAD_TIME_TOO_SHORT`, and `ERR_CAPACITY_FULL` rejections apply in their usual order. On success the old day's `booked_head` decreases by `head_count`, the new day's increases by the same amount (recomputing each day's `OPEN` or `FULL` standing), and `appointment_date` is rewritten to the new day's date. The quoted deposit does not change when the date moves.

Cancellation is available to the booking customer and to staff. While the appointment is still `PENDING_DEPOSIT`, cancellation is unconditional: the day's `booked_head` is released, `refund_cents` is set to whatever deposit cash has been received — normally zero, since any successful deposit payment would already have confirmed the booking — and the appointment becomes `CANCELLED`. Once `CONFIRMED`, cancellation is permitted only while every animal of the appointment is still `EXPECTED`; if any animal has already progressed past drop-off the attempt is rejected with `ERR_INVALID_STATE`. A confirmed cancellation voids each expected animal, and each voided animal releases one head of capacity back to the day. The refund follows the seven-day policy: if the whole-day count from the current date to `appointment_date` is at least seven, `refund_cents` is the full `deposit_paid_cents`; fewer than seven days out, the deposit is forfeited and `refund_cents` is zero. The cancellation request may carry an optional `reason` note.

Two system-driven exits close out bookings that quietly die. If the logical clock passes `deposit_due_at` while the appointment remains `PENDING_DEPOSIT`, the daily sweep moves it to `EXPIRED`, releases its head count back to the day, and charges no strike — no animals ever existed and no money changed hands. If a `CONFIRMED` appointment's date passes with nothing dropped off, staff may mark the no-show manually or let the sweep do it; the manual mark is only allowed on or after `appointment_date`, and an attempt before that date is rejected with `ERR_NO_SHOW_PREMATURE`. Either path requires every animal of the appointment to still be `EXPECTED` — a partial drop-off means the appointment is live, not abandoned. The no-show voids each expected animal with the usual per-head capacity release, forfeits the deposit (`refund_cents` stays zero and the plant retains `deposit_paid_cents`), increments the customer's `no_show_strikes` by one, and recomputes the customer's standing, which flips to `ELEVATED_DEPOSIT` on the first strike and `BLOCKED` on the second.

### 3.3. From Drop-Off to the Rail: Receiving, Slaughter, and Hanging

On the morning of the appointment, staff receive each animal at the scale. Receiving records the plant-assigned `tag_id` and the `live_weight_lbs` to one decimal place, stamps `received_at`, and moves the animal from `EXPECTED` to `RECEIVED`. The tag is the carcass's identity for the rest of its journey: `tag_id` must be unique among all animals not in `VOIDED` — a duplicate is refused with `ERR_DUPLICATE_TAG` — and once set it is immutable, following the carcass through every later transition. Receiving also drives the appointment's bubble-up: when the last `EXPECTED` animal of an appointment is received, the appointment moves automatically from `CONFIRMED` to `COMPLETED`.

From there the animal walks the floor in order. Recording slaughter moves `RECEIVED` to `SLAUGHTERED` and stamps `slaughtered_at`. Recording the hot hanging weight moves `SLAUGHTERED` to `HANGING`: the request carries `hanging_weight_lbs` to one decimal place, and the system stamps `weighed_at`, which starts the hang-time clock that gates fabrication. Each of these staff actions is available to `PlantOperator` and `PlantManager`, and each increments the animal's `version` like any other mutation.

### 3.4. Splitting the Carcass and Capturing Cut Instructions

Custom-exempt work routinely divides one carcass among several buyers — a rancher sells halves or quarters to neighbors, each of whom becomes an owner of record. A share is added to an animal by the booking customer or by staff, naming the buyer through `owner_customer_id`, the portion through `share_fraction` (greater than zero, at most 1.0, and no more than three decimal places), and the declared end use through `intended_use`, which is either `OWNER_USE` or `RESALE`. The share is created in `PENDING` with its `animal_id` bound by the path of the creation request. Shares can be listed with optional `animal_id`, `owner_customer_id`, and `status` filters. Adding a share that would push the animal's fraction sum above 1.0 is rejected with `ERR_SPLIT_OVER_ALLOCATED`. While the split is still being worked out, a `PENDING` share may be removed — the booking customer or staff deletes it, the animal's allocated fraction decreases accordingly, and the response carries no content. Once any share of the animal has been confirmed, deletion is no longer a state the share can leave from, and the removal attempt fails as an invalid state.

Finalizing the split is a staff action taken once the animal is `HANGING` — attempting it earlier fails with `ERR_INVALID_STATE` — and only when the fractions across the animal's shares sum to exactly 1.0, with a shortfall rejected as `ERR_SPLIT_UNDER_ALLOCATED`. Finalization turns every `PENDING` share `CONFIRMED` and performs two allocations. First, each share's `share_hanging_weight_lbs` is computed as the animal's `hanging_weight_lbs` multiplied by the share's `share_fraction`, rounded half-up to one decimal place, share by share in creation order; if the rounded weights do not sum back to the animal's hanging weight, the residual is assigned to the share with the largest `share_fraction` — ties broken in favor of the earliest-created share — so the allocated weights sum to the hanging weight exactly. Each share's `estimated_share_weight_lbs` is also recorded: the animal's `live_weight_lbs` multiplied by the species dressing percentage and by the share's fraction, rounded half-up to one decimal. Second, the appointment's collected deposit is distributed so it can be credited at settlement: because both deposit quote variants scale linearly with head count, each animal's pool is exactly the appointment's `deposit_paid_cents` divided by `head_count`, rounded half-up to a whole cent, with any residual cents going to the earliest-created animal of the appointment; the pool then flows to the animal's shares in creation order, each share's `deposit_credit_cents` being the pool multiplied by its `share_fraction` rounded half-up to a whole cent per share first, and any leftover difference — a cent or two in either direction — reconciled afterward onto the largest-fraction share, again breaking ties by earliest creation, so the credits across an animal's shares sum to the pool exactly. Finalization also creates, for each share, one Invoice in `OPEN` status and one LabelRecord in `PENDING` status, both described in later subsections.

Every share needs exactly one set of cutting instructions. The share's owner creates the cut sheet — staff cannot do it for them — supplying `grind_pct` as a whole-number percentage between 0 and 100, a `package_weight_lbs` target of at least 1.0 pounds to one decimal, an optional `steak_thickness_in` between 0.5 and 2.0 inches (absent by default), and an optional free-text `notes` for the butcher (empty by default). The sheet's `share_id` is bound by the creation path, and a second sheet for the same share is refused with `ERR_CUT_SHEET_EXISTS`. A new sheet starts in `DRAFT`; sheets can be listed filtered by `share_id` or `status`.

Submitting the sheet signals the instructions are final enough to cut against. Submission requires the share to still be in `PENDING` or `CONFIRMED` — once fabrication has begun the attempt fails with `ERR_INVALID_STATE` — and it enforces yield feasibility: a `grind_pct` above 60 percent of the share's trimmable weight cannot be physically met, so submission with such a value is rejected with `ERR_YIELD_INFEASIBLE`. A successful submission moves the sheet from `DRAFT` to `SUBMITTED`. The owner may still revise instructions any time before fabrication locks them: revising requires `expected_cut_sheet_version` per §2.7, applies any provided instruction fields among `grind_pct`, `package_weight_lbs`, `steak_thickness_in`, and `notes`, and — when issued against a `SUBMITTED` sheet — returns the sheet to `DRAFT` so it must be submitted anew; issued against a `DRAFT` sheet it simply updates content in place. This submit–revise cycle can repeat freely until the animal enters fabrication.

### 3.5. Fabrication, Freezer Capacity, and Storage Accrual

Starting fabrication is the point of no return for instructions, and three preconditions guard it, surfacing in the order fixed by §2.8. The split must be finalized — at least one `CONFIRMED` share covering a fraction sum of exactly 1.0 — else `ERR_SPLIT_NOT_FINALIZED`. The carcass must have aged enough: the current logical time must be at least three full days past `weighed_at`, else `ERR_MIN_HANG_NOT_MET`. And every `CONFIRMED` share of the animal must have its cut sheet in `SUBMITTED` status, else `ERR_CUT_SHEET_MISSING` — a sheet left in `DRAFT` blocks the knife just as surely as a missing one. When all three hold, the animal moves from `HANGING` to `CUTTING` and every `SUBMITTED` cut sheet of its shares locks to `LOCKED`, ending the revision cycle.

Completing fabrication turns carcasses into boxed shares, and the freezer is the binding constraint. The plant's freezer holds four units; each share occupies exactly one unit, so `freezer_units` is always 1. Before the transition is allowed, the count of storage records currently `STORED` plus the number of this animal's `CONFIRMED` shares must not exceed four, else the completion is rejected with `ERR_FREEZER_FULL`. Occupancy windows are half-open: a record occupies its unit from its `ready_at` instant up to but not including its `picked_up_at` instant, so a pickup recorded at a given instant frees the unit for a share that becomes ready at that same instant. On success each `CONFIRMED` share moves to `READY`, the animal moves from `CUTTING` to `READY`, one StorageRecord per share springs into existence in `STORED` status with `ready_at` stamped to the current logical instant, and each share's invoice is recomputed against actual hanging weights as §3.6 describes — the invoice's status itself is unchanged, typically still `OPEN`.

From `ready_at` onward the storage clock runs. A record's `days_stored` counts whole calendar days from `ready_at` to the present while it remains `STORED`, and from `ready_at` to `picked_up_at` once picked up. The first seven days are free; every day beyond the seventh bills at 500 cents. The `accrued_fee_cents` is therefore the billable-day count — `days_stored` minus seven, never below zero — multiplied by 500. Accrual is recomputed whenever the passage of time is observed: reading a single storage record recomputes `days_stored` and `accrued_fee_cents` as of the current logical instant before responding, and the same as-of-now recomputation happens at payment, at pickup, and during the daily sweep. Storage records can be listed with optional `share_id` and `status` filters, and `picked_up_at` stays unset until the customer walks out with the boxes.

### 3.6. Invoices, Payments, and Settlement

One invoice per share is created at split finalization, carrying the `share_id` it bills for and the `species` copied from the animal for rate lookup. Processing is priced on hanging weight under a two-tier schedule: weight up to and including 200 pounds bills at the species' first-tier rate, and any weight above 200 pounds bills at the second-tier rate on the excess only. The first-tier rates are 95 cents per pound for `BEEF`, 85 for `HOG`, and 110 for `LAMB` and `GOAT`; the second-tier rates are 85 for `BEEF`, 75 for `HOG`, and 95 for `LAMB` and `GOAT`. At or under the 200-pound boundary the fee is the weight multiplied by the first-tier rate, rounded half-up to a whole cent; above the boundary the fee is exactly 200 pounds at the first-tier rate plus the excess weight multiplied by the second-tier rate, that excess portion rounded half-up to a whole cent. The slaughter component, `slaughter_share_cents`, is the species slaughter fee — 12000 cents for `BEEF`, 6000 for `HOG`, 4500 for `LAMB` and `GOAT` — multiplied by the share's `share_fraction`, rounded half-up to a whole cent.

The invoice carries two totals because it is quoted before actual weights exist and billed after. The quoted figure, `provisional_total_cents`, is computed once at creation and never recomputed: it runs the tiered processing schedule against the share's `estimated_share_weight_lbs` rather than the actual hanging weight, adds the same `slaughter_share_cents`, assumes zero storage and zero surcharge, and subtracts the share's `deposit_credit_cents`. The live figure, `total_cents`, is the final-variant sum: `processing_fee_cents` computed from the share's actual `share_hanging_weight_lbs`, plus `slaughter_share_cents`, plus the storage component — the invoice's `storage_cents` accrued as of the current instant, or zero when `storage_waived` is true — plus `surcharge_cents`, minus `deposit_credit_cents`. Whenever the actual hanging weight differs from the estimate, the provisional and final totals diverge. `amount_paid_cents` starts at zero and accumulates recorded payments; `amount_due_cents` is `total_cents` minus `amount_paid_cents`, floored at zero. A fresh invoice has `surcharge_cents` at zero and `storage_waived` false, and opens in `OPEN` status. Invoices can be listed with optional `share_id` and `status` filters, with customers seeing only invoices on shares they own.

Recording a payment is open to the share-owning customer and to staff. The invoice must be in `OPEN`, `PARTIALLY_PAID`, or `COLLECTIONS` — an invoice already `PAID` is terminal and rejects further payments with `ERR_INVALID_STATE` — and the tendered `amount_cents` must be at least one cent, else `ERR_INVALID_REQUEST`. Before the payment is applied, the invoice's `storage_cents` is recomputed as of the current instant under the final variant, so a customer paying on day ten of storage sees the three billable days in their balance; `total_cents` and `amount_due_cents` are recomputed with it. A payment smaller than the amount due moves the invoice to `PARTIALLY_PAID`; a payment covering the full amount due moves it to `PAID`, whether from `OPEN`, `PARTIALLY_PAID`, or `COLLECTIONS`. Settling a collections invoice clears the debt but does not un-abandon the share — forfeited meat stays forfeited.

A `PlantManager` may forgive freezer charges on an invoice as an override: waiving sets `storage_waived` to true, and the total and amount due are recomputed with the storage component forced to zero. The waiver does not touch the storage record's own accrual; it zeroes only the invoice's storage component.

### 3.7. Label Approval and Customer Pickup

The compliance gate stands between the freezer and the loading dock. Every share's label record is created at split finalization in `PENDING` status with `program` fixed to `CUSTOM_EXEMPT` and `label_text` computed to begin with the exact string `NOT FOR SALE` followed by the owner name and a description of the share; custom-exempt product may not bear an inspection legend, so no inspected variant of the label exists. Staff approve the label only when the share's `intended_use` is `OWNER_USE` — product labeled not for sale may never be resold, and approval for a `RESALE` share is rejected with `ERR_RESALE_LABEL_FORBIDDEN`. Approval moves the record from `PENDING` to `APPROVED`, and label records can be listed with `share_id` and `status` filters.

Pickup is a staff action on the storage record, and two gates apply in the order of §2.8: the share's label must be `APPROVED`, else `ERR_LABEL_NOT_APPROVED`, and the share's invoice must stand `PAID` after its storage has been recomputed as of the pickup instant — unpaid accrual since the last payment still blocks the door, surfacing as `ERR_INVOICE_NOT_PAID`. When both gates pass, the record moves from `STORED` to `PICKED_UP`, `picked_up_at` is stamped, and the invoice's `storage_cents` is finalized to exactly the accrual at that instant — it will never grow again. The share cascades from `READY` to `PICKED_UP`, the freed freezer unit becomes available to anything ready at that same instant under the half-open window rule, and when every share of the animal has reached a terminal state the animal bubbles up from `READY` to `COMPLETE`.

### 3.8. No-Shows, Abandonment, and the Daily Ops Checkpoint

Meat that nobody collects is both a freezer problem and a balance-sheet problem, and the plant's answer is the abandoned-meat policy. When a storage record's `days_stored` exceeds 21 — from the 22nd day after `ready_at` onward — the record is swept to `ABANDONED`. The abandonment cascades in a fixed chain: the share moves from `READY` to `FORFEITED`; that forfeiture drives the share's invoice, whether `OPEN` or `PARTIALLY_PAID`, into `COLLECTIONS` with `surcharge_cents` set to 5000 cents and the total recomputed; and the invoice entering collections charges the owning customer's `no_show_strikes` by one, recomputing their standing so a second strike of any kind blocks them from further bookings. An already-`PAID` invoice has no balance to collect, so the cascade's invoice step applies only while a balance remains open.

The daily operations checkpoint is a staff-invoked sweep that runs three jobs in one pass: it expires every `PENDING_DEPOSIT` appointment whose `deposit_due_at` has passed, releasing the reserved head count without charging a strike; it marks `NO_SHOW` every `CONFIRMED` appointment whose date has passed with all animals still `EXPECTED`, running the full no-show cascade of §3.2 including the forfeited deposit and the customer strike; and it sweeps to `ABANDONED` every storage record past the 21-day limit with the full abandonment chain above. The sweep responds with three lists — `expired_appointment_ids`, `no_show_appointment_ids`, and `abandoned_storage_ids` — so the front desk can see exactly what the pass touched.

Strikes are the memory of the system, and they never decay. A first strike from either a no-show or an abandonment moves the customer to `ELEVATED_DEPOSIT`, which changes the deposit economics of every future booking per §3.1; a second strike moves them to `BLOCKED`, which refuses new bookings outright with `ERR_CUSTOMER_BLOCKED`; and independently of the strike count, any invoice sitting in `COLLECTIONS` refuses new bookings with `ERR_OUTSTANDING_BALANCE` until the debt is settled. The two mechanisms compose: a customer who abandons one share carries both a strike and a collections invoice, and must clear the invoice before the calendar opens to them again — under the elevated deposit terms their strike has earned.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource or trigger a state transition return `200 OK`; the share-removal operation returns `204 No Content` with an empty data payload. The complete HTTP contract is summarized below; request payloads, preconditions, and side effects are specified in §2 and §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/locker/customers` | Register a customer (front desk) | PlantOperator, PlantManager |
| GET | `/locker/customers` | List customers | PlantOperator, PlantManager |
| GET | `/locker/customers/{id}` | Read one customer | PlantOperator, PlantManager, Customer |
| POST | `/locker/capacity-days` | Open a slaughter capacity day | PlantManager |
| GET | `/locker/capacity-days` | List capacity days (customers browse open days) | PlantOperator, PlantManager, Customer |
| POST | `/locker/appointments` | Book a slaughter appointment; computes the deposit quote | Customer, PlantOperator, PlantManager |
| GET | `/locker/appointments` | List appointments (customers see only their own) | PlantOperator, PlantManager, Customer |
| GET | `/locker/appointments/{id}` | Read one appointment | PlantOperator, PlantManager, Customer |
| POST | `/locker/appointments/{id}/pay-deposit` | Pay the booking deposit; confirms the appointment and creates expected animals | Customer |
| POST | `/locker/appointments/{id}/cancel` | Cancel a pending or confirmed appointment; refund per the cancellation policy | Customer, PlantOperator, PlantManager |
| POST | `/locker/appointments/{id}/reschedule` | Move the booking to a different capacity day (OCC-guarded self-loop) | Customer |
| POST | `/locker/appointments/{id}/no-show` | Staff marks a no-show on or after the appointment date | PlantOperator, PlantManager |
| GET | `/locker/appointments/{id}/animals` | List the animals of an appointment | PlantOperator, PlantManager, Customer |
| GET | `/locker/animals/{id}` | Read one animal | PlantOperator, PlantManager, Customer |
| POST | `/locker/animals/{id}/receive` | Drop-off: assign identification tag and live weight | PlantOperator, PlantManager |
| POST | `/locker/animals/{id}/slaughter` | Record slaughter | PlantOperator, PlantManager |
| POST | `/locker/animals/{id}/weigh` | Record hanging weight; starts the hang-time clock | PlantOperator, PlantManager |
| POST | `/locker/animals/{id}/start-fabrication` | Start cutting; requires finalized split, all cut sheets submitted, and minimum hang; locks cut sheets | PlantOperator, PlantManager |
| POST | `/locker/animals/{id}/complete-fabrication` | Finish cutting and wrapping; shares become ready, storage records created, invoices finalized | PlantOperator, PlantManager |
| POST | `/locker/animals/{id}/shares` | Add a split-carcass ownership share to the animal | Customer, PlantOperator, PlantManager |
| POST | `/locker/animals/{id}/shares/finalize` | Finalize the split: validates the fraction sum, allocates hanging weight and deposit credit, creates invoices and label records | PlantOperator, PlantManager |
| GET | `/locker/shares` | List shares (customers see only shares they own) | PlantOperator, PlantManager, Customer |
| GET | `/locker/shares/{id}` | Read one share | PlantOperator, PlantManager, Customer |
| DELETE | `/locker/shares/{id}` | Remove a pending share (split correction before finalize) | Customer, PlantOperator, PlantManager |
| POST | `/locker/shares/{id}/cut-sheet` | Create the cut sheet for a share (one per share) | Customer |
| GET | `/locker/cut-sheets` | List cut sheets | PlantOperator, PlantManager, Customer |
| GET | `/locker/cut-sheets/{id}` | Read one cut sheet | PlantOperator, PlantManager, Customer |
| POST | `/locker/cut-sheets/{id}/submit` | Submit cut instructions (yield feasibility checked) | Customer |
| POST | `/locker/cut-sheets/{id}/revise` | Revise instructions (OCC-guarded); from submitted returns the sheet to draft | Customer |
| GET | `/locker/invoices` | List invoices (customers see only invoices on shares they own) | PlantOperator, PlantManager, Customer |
| GET | `/locker/invoices/{id}` | Read one invoice | PlantOperator, PlantManager, Customer |
| POST | `/locker/invoices/{id}/payments` | Record a payment; recomputes as-of-now storage before applying; may flip to partially paid or paid | Customer, PlantOperator, PlantManager |
| POST | `/locker/invoices/{id}/waive-storage` | Waive accrued storage fees on the invoice (manager override) | PlantManager |
| GET | `/locker/storage-records` | List freezer storage records | PlantOperator, PlantManager, Customer |
| GET | `/locker/storage-records/{id}` | Read one storage record (accrual recomputed as-of now on read) | PlantOperator, PlantManager, Customer |
| POST | `/locker/storage-records/{id}/pickup` | Record customer pickup; requires approved label and paid invoice; finalizes storage fee | PlantOperator, PlantManager |
| GET | `/locker/labels` | List label records | PlantOperator, PlantManager, Customer |
| GET | `/locker/labels/{id}` | Read one label record | PlantOperator, PlantManager, Customer |
| POST | `/locker/labels/{id}/approve` | Compliance approval of the custom-exempt not-for-sale label; rejected for resale shares | PlantOperator, PlantManager |
| POST | `/locker/ops/run-daily` | Ops-run checkpoint: expires overdue pending appointments, auto-marks no-shows, sweeps abandoned storage | PlantOperator, PlantManager |
| POST | `/_clock/set_current_utc` | Set the test-driving logical clock | PlantManager |

## 5. Error Code Catalogue

Trigger conditions for each error are specified in the narratives of §2 and §3.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_CUSTOMER_BLOCKED` | 403 |
| `ERR_OUTSTANDING_BALANCE` | 402 |
| `ERR_CAPACITY_FULL` | 409 |
| `ERR_LEAD_TIME_TOO_SHORT` | 422 |
| `ERR_DEPOSIT_INSUFFICIENT` | 402 |
| `ERR_DUPLICATE_TAG` | 409 |
| `ERR_SPLIT_OVER_ALLOCATED` | 422 |
| `ERR_SPLIT_UNDER_ALLOCATED` | 422 |
| `ERR_SPLIT_NOT_FINALIZED` | 409 |
| `ERR_CUT_SHEET_EXISTS` | 409 |
| `ERR_CUT_SHEET_MISSING` | 422 |
| `ERR_YIELD_INFEASIBLE` | 422 |
| `ERR_MIN_HANG_NOT_MET` | 422 |
| `ERR_NO_SHOW_PREMATURE` | 422 |
| `ERR_RESALE_LABEL_FORBIDDEN` | 422 |
| `ERR_LABEL_NOT_APPROVED` | 409 |
| `ERR_INVOICE_NOT_PAID` | 402 |
| `ERR_FREEZER_FULL` | 409 |
