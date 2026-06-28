# ATM Cash Logistics API — Product Requirements Document

## 1. Introduction

An independent ATM operator runs a fleet of cash-dispensing machines across host sites it does not own — a deli counter, a convenience store, a hotel lobby — and earns revenue from two streams: the surcharge a consumer agrees to pay at the screen, and the interchange the card network remits per withdrawal. Behind every machine sits a logistics problem that never stops moving: cash must be forecast, drawn from an armored vault, carried under custody by a route carrier, loaded into physical cassettes, dispensed note by note, then counted back and reconciled against what the machine claims it dispensed. This API is the system of record for that chain of custody, from the moment cash is provisioned into a vault to the moment a settlement run pays a host merchant its commission split.

The platform must hold three things in balance at once. First, **cash conservation** — every cent provisioned into a vault is always either resting on hand, in transit on an armored truck, or resident inside a machine's cassettes, and the system must be able to prove that invariant after every dispatch, load, recall, and reconciliation. Second, **revenue integrity** — surcharge and interchange must be swept into immutable settlement runs that never double-count a withdrawal, and the host merchant's commission must be computed against a contract that can cap monthly payout. Third, **regulatory compliance** — no machine may take a live transaction until a compliance officer has approved a fee disclosure whose printed surcharge matches the machine and falls under the jurisdiction's statutory cap.

This document specifies the entities, state machines, calculations, validations, and access-control rules that together implement that system. It is written for the engineers who will build the service and is the single authoritative description of its behavior.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request to the API must carry two mandatory HTTP headers: `X-User-ID`, identifying the acting operator, and `X-User-Role`, declaring the capacity in which they act. A request missing either header, or carrying a header the server cannot interpret, is rejected with `ERR_UNAUTHENTICATED`. When the headers are present but the declared role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE`.

The system recognizes exactly five roles, spelled precisely: `PlatformAdmin`, `VaultController`, `FieldTech`, `SettlementOfficer`, and `ComplianceOfficer`. A `PlatformAdmin` provisions the configuration backbone — merchants, vaults, routes, locations, and machines — and may read everywhere as a setup superset. A `VaultController` owns the vault and the armored dispatch lifecycle. A `FieldTech` owns on-site work: confirming loads, taking cash counts, closing out reconciliations, and working service tickets. A `SettlementOfficer` owns settlement runs and the commission statements they generate. A `ComplianceOfficer` owns the drafting, approval, and rejection of fee disclosures.

All five roles use an opaque identity model. For each of `PlatformAdmin`, `VaultController`, `FieldTech`, `SettlementOfficer`, and `ComplianceOfficer`, the value of `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity and is never compared to any entity's `id` for ownership purposes. The server may, however, record an operator's identifier where a workflow demands it: when a `FieldTech` acknowledges a service ticket, the server writes that tech's `X-User-ID` into the ticket's `assigned_tech_id`, and later resolution and reopening are gated on the acting tech matching that recorded owner. That single ownership check is the only place an `X-User-ID` value re-enters business logic.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return. If not provided, it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0, with a minimum of 0.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order.

Paginated and non-paginated list-based responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Almost every resource in the system carries a standard set of system-managed fields:

- **`id`** — a unique, server-minted identifier formatted as a UUID, with no type prefix.
- **`created_at`** — an ISO 8601 UTC timestamp with three fractional digits, recording when the resource was first created.
- **`updated_at`** — an ISO 8601 UTC timestamp recording when the resource was last modified; refreshed on every mutation, including server-driven recomputation of derived fields.
- **`version`** — a system-managed integer that begins at its initial value and increments by one on every modification to the resource. It is the basis for the optimistic concurrency control described in §2.8.

There is one deliberate exception. A `Transaction` is an append-only event record. It carries only `id` and `created_at`; it has neither an `updated_at` nor a `version` field, because once posted it is never mutated. Every other entity — `Location`, `SiteMerchant`, `ArmoredRoute`, `Vault`, `ATM`, `Cassette`, `ReplenishmentOrder`, `CashCount`, `ServiceTicket`, `SettlementRun`, `CommissionStatement`, and `FeeDisclosure` — carries the full set of four common fields.

### 2.5. Derived-Field Recomputation and State Propagation

A great deal of this system's behavior is in its cascades: a single operator action frequently mutates several entities at once, and those secondary mutations are not optional side notes — they are part of the contract. Whenever an operation recomputes a derived field or advances a dependent entity's state, that dependent entity's `updated_at` is refreshed and, where it carries one, its `version` is incremented, exactly as if the client had edited it directly.

The most important propagation rule concerns the machine's two state dimensions. An `ATM` carries two completely independent status fields. Its `operational_status` tracks the jam/fault dimension and takes the values `IN_SERVICE`, `FAULTED`, or `OUT_OF_SERVICE`. Its `cash_status` tracks the replenishment-and-reconciliation dimension and takes the values `EMPTY`, `AWAITING_LOAD`, `LOADED`, `LOW`, or `RECONCILING`. These two dimensions never interfere with each other's enumeration: a machine can be `FAULTED` and `LOADED` at the same time, and a fault never changes the cash dimension nor vice versa. The one place they meet is a single guard — confirming a load is forbidden while the machine is `OUT_OF_SERVICE` — described in §3.

Whenever a vault's cash position changes — on dispatch, on load confirmation, on recall, or on reconciliation close-out — the vault's three derived cash figures (`balance_cents`, `in_transit_cents`, `in_machine_cents`) are recomputed together so they always agree with the underlying replenishment orders. Likewise, a machine's `loaded_cents` and `dispensed_cents_since_load`, and each cassette's `loaded_cents` and `dispensed_cents`, are recomputed at the events described in §3 rather than stored as free-standing inputs.

### 2.6. Nested Resource Retrieval and Existence Ordering

Several endpoints address a resource through a path that names more than one identifier — for example, closing out a specific cash count names both the owning machine and the count. The server validates path identifiers left to right. It confirms the first identifier refers to an existing resource before looking at the second, and rejects the request with `ERR_NOT_FOUND` against the first identifier that does not resolve. This same existence pass extends to foreign keys carried in a request body: after the path resolves, every referenced entity named in the body must exist, or the request is rejected with `ERR_NOT_FOUND`. Existence checking runs after authentication and authorization but before any business rule.

The system also applies two cross-cutting validations in a fixed relative order. Authentication (`ERR_UNAUTHENTICATED`) is checked first, then authorization (`ERR_FORBIDDEN_ROLE`), then existence (`ERR_NOT_FOUND`). After existence resolves, every create or transition request must have its required body fields present and well-typed and every enum-valued field set to a recognized member, or the request is rejected with `ERR_INVALID_REQUEST`. Only then do the more specific business and state rules of §3 run. Among those, any attempt to drive an entity through a transition that is not defined from its current state — settling a run that is already `SETTLED`, acknowledging a ticket that is not `OPEN`, approving a disclosure that is not `DRAFT`, and the like — is rejected with `ERR_INVALID_STATE`, the generic guard that backs every state machine described below.

### 2.7. Monetary Precision and Cash Conservation

All monetary quantities in this system are integers denominated in cents. There are no fractional cents anywhere in the API; nothing is stored or returned as a decimal dollar amount. Where a calculation involves division — computing a percentage commission, or averaging a daily dispense rate — the rule for dropping the fractional part is stated explicitly with the calculation in §3, and is always a floor (round toward zero for the non-negative quantities involved) unless that calculation says otherwise. Note-denomination rounding for forecasts rounds **up** to a whole number of notes, as §3 specifies.

A vault obeys a strict conservation invariant. At the moment a vault is created it is given a `provisioned_cents` baseline — the total cash poured into its custody chain — and that baseline is conserved forever. At all times the sum of the vault's on-hand `balance_cents`, its `in_transit_cents`, and its `in_machine_cents` equals `provisioned_cents`. On-hand balance is the provisioned baseline minus what is currently in transit minus what is currently resident in machines; in-transit is the total order amount of every replenishment order this vault is currently funding that has been dispatched but not yet loaded; in-machine is the total order amount of every order this vault funded that has been loaded but not yet reconciled out. Money only moves between these three buckets — it is never created or destroyed — which is why every dispatch, load, recall, and close-out adjusts two buckets in equal and opposite amounts.

### 2.8. Optimistic Concurrency on Vault Dispatch

Dispatching a replenishment order draws cash from a shared vault, and several orders can legitimately draw on the same vault. To keep two writers from each spending against a vault balance only one of them actually has, dispatch is guarded by optimistic concurrency control on the vault's `version`. A dispatch request must carry `expected_vault_version`, the value of the target vault's `version` that the client last observed when it read the vault. Before the dispatch debits anything, the server compares `expected_vault_version` against the vault's current `version`. If they do not match — because some other dispatch or some recall compensation has advanced the vault's `version` since the client's last read, changing the on-hand balance out from under it — the request is rejected with `ERR_STALE_VERSION` and an HTTP 412 status, and no cash moves. This is the only endpoint that takes a version field; every other mutating endpoint in the system processes without an OCC check.

### 2.9. Fee-Disclosure Compliance Gate

No machine may take a live withdrawal, and no settlement run may settle, until that machine has an approved fee disclosure on file. A fee disclosure binds a printed surcharge to a machine under a jurisdiction's statutory cap, and approving one is the act that "turns the machine on" for revenue purposes by writing the disclosure's `id` into the machine's `fee_disclosure_id`. The detailed approval preconditions, the jurisdiction caps, and the supersession behavior live in §3, because they are part of the compliance workflow rather than a standalone envelope rule.

## 3. Business Logic & Workflows

### 3.1. Provisioning the Network: Merchants, Vaults, Routes, Locations

Everything begins with configuration, and configuration is the `PlatformAdmin`'s domain. The admin first creates the commission counterparties and the cash supply chain, then stitches sites and machines onto them.

A **site merchant** is the host business that owns the commission contract for a site. Creating one captures the merchant's `legal_name` and the commercial terms of the split: `commission_pct_bps` is the percentage rate expressed in basis points of net operator revenue, valid from 0 to 10000 inclusive, where 10000 basis points is one hundred percent; `commission_flat_per_wd_cents` is a flat amount per withdrawal in cents that acts as the floor in a "whichever is greater" arrangement; and `commission_monthly_ceiling_cents` caps how much commission the merchant can be paid across a single calendar month. The contract's `commission_basis` pins which formula governs the split and may be `GREATER_OF`, `PCT_ONLY`, or `FLAT_ONLY`; when omitted at creation it defaults to `GREATER_OF`. A merchant also carries a `payout_status` of `ACTIVE` or `SUSPENDED`, which the system initializes to `ACTIVE`. An admin may later suspend a merchant, flipping `payout_status` to `SUSPENDED`; a suspended merchant accrues zero commission, as §3.7 details.

A **vault** is created with a human-readable `name` and a `provisioned_cents` baseline. At creation the server seeds the derived position so the vault is entirely on-hand: `balance_cents` equals `provisioned_cents`, while `in_transit_cents` and `in_machine_cents` both start at zero.

An **armored route** is the carrier path that draws cash from one vault and services sites. It is created with a `carrier_name` and a `vault_id` naming the vault it draws from. A route carries a `status` of `ACTIVE` or `PAUSED`, initialized to `ACTIVE`; pausing a route flips its `status` to `PAUSED` so that no new dispatch can be scheduled against it. Routes can be listed and filtered by the `vault_id` they draw from.

A **location** is a host site. It is created with a `name`, a `jurisdiction_code`, a `site_merchant_id` naming the merchant that owns its commission contract, a `route_id` naming the armored route that services it, and a street `address`. The `jurisdiction_code` is one of `CA`, `NY`, `TX`, or `FL`, and it determines both the regulatory surcharge cap and the disclosure rules that apply to every machine at the site. Locations can be listed and filtered by `site_merchant_id` or `route_id`.

### 3.2. Commissioning a Machine and Its Cassettes

A `PlatformAdmin` provisions an **ATM** at a location by supplying a `serial_no`, the hosting `location_id`, and the operator `surcharge_cents` to be charged per withdrawal. The note value the machine dispenses is given by `note_denomination_cents`; when omitted it defaults to 2000, meaning the machine dispenses twenty-dollar bills. The machine's serial is its physical fingerprint: `serial_no` must be unique across every machine in the system, and a collision is rejected with `ERR_DUPLICATE_SERIAL`. A freshly provisioned machine starts with `operational_status` of `IN_SERVICE` and `cash_status` of `EMPTY`; its computed counters `monthly_wd_count`, `loaded_cents`, and `dispensed_cents_since_load` all start at zero, and its `fee_disclosure_id` is null until compliance approves a disclosure for it. Reading a machine returns all of these computed fields alongside both status dimensions. Machines can be listed and filtered by `location_id` or by `fee_disclosure_id`.

Inside a machine sit physical **cassettes**. A cassette is added to a machine by naming its `position`, one of the four physical slots `C1`, `C2`, `C3`, or `C4`. Each cassette tracks two computed cash figures — `loaded_cents`, the cash placed in it by the most recent confirmed load, and `dispensed_cents`, the running total charged against it since that load — plus a `balance_status` of `BALANCED`, `OVER`, or `SHORT` that is set at reconciliation and starts at `BALANCED`. Cassettes for a machine can be listed; the listing reaches them by their owning `atm_id`.

### 3.3. Forecasting the Cash Load

Before scheduling a replenishment, a `VaultController`, `FieldTech`, or `PlatformAdmin` can ask the system to project how much cash a machine will need. The forecast is a read-only projection — it mutates nothing — and it accepts two inputs: a `basis` selecting the forecast variant, and `days_until_next_visit`, the integer number of days until the next planned service, which must be at least 1. A `days_until_next_visit` below 1 is rejected with `ERR_VALIDATION`. The response reports the rounded `forecast_cents`, the `avg_daily_dispense_cents` the variant computed, and the `basis` that was used.

Both variants share the same outer shape. A raw figure is the average daily dispense multiplied by `days_until_next_visit` and then by a safety factor of 1.25 (a twenty-five percent buffer over the bare projection). That raw figure is then rounded **up** to the nearest whole multiple of the machine's `note_denomination_cents`, because a machine can only be loaded in whole notes — so a raw figure of any amount that is not already a clean multiple of the note value is lifted to the next multiple. The two variants differ only in how the average daily dispense is computed.

Under the **forward-looking** variant, selected when `basis` is `FORWARD`, the average daily dispense is the sum of the `amount_cents` of every `WITHDRAWAL` transaction whose creation time falls in the half-open window beginning fourteen days before the current logical clock instant and ending at — but not including — that instant, divided by a fixed divisor of fourteen. This window counts every withdrawal in the trailing fourteen days regardless of where replenishment boundaries fell, giving a steady-state estimate.

Under the **chronological** variant, selected when `basis` is `CHRONOLOGICAL`, the average daily dispense counts only actuals since the machine's most recent confirmed load. It is the sum of the `amount_cents` of every `WITHDRAWAL` transaction posted at or after the timestamp of the most recent load confirmation, divided by the number of whole days elapsed since that load. The number of whole days elapsed is the elapsed time from the load confirmation to the current clock instant, divided into whole days by discarding any partial day, but never less than one day. If the machine has never been loaded, the chronological variant cannot anchor itself and falls back to computing the forward-looking figure instead. When `basis` is omitted, the system treats the request under the forward-looking variant as the default.

### 3.4. Scheduling and Dispatching a Replenishment

A **replenishment order** carries cash from a vault into a machine, and it walks a branching lifecycle with a compensation path. A `VaultController` or `PlatformAdmin` schedules one by naming the `atm_id` to replenish, the `route_id` that will fulfill it, the `order_amount_cents` of cash to load, and a service window bounded by `service_window_start` and `service_window_end` as ISO 8601 UTC instants. The order may also carry a `forecast_basis` recording which forecast variant — `FORWARD` or `CHRONOLOGICAL` — produced its amount; when omitted it defaults to `FORWARD`. A newly scheduled order is born in `SCHEDULED` status. Its `vault_id` is not supplied by the client; it is resolved from the route at dispatch time.

The pivotal action is **dispatch**, performed by a `VaultController`, which advances the order from `SCHEDULED` to `DISPATCHED`. Dispatch carries a single body field, `expected_vault_version`, the OCC token described in §2.8. Dispatch runs a gauntlet of preconditions, and their relative ordering matters because the error a client sees should be the most specific one that applies. Existence of the order, the route, and the resolved vault is settled first per §2.6. Then the business checks run: the fulfilling route must be `ACTIVE`, or the dispatch is rejected with `ERR_ROUTE_PAUSED`; the `order_amount_cents` must be an exact whole-number multiple of the target machine's `note_denomination_cents`, or it is rejected with `ERR_AMOUNT_NOT_DENOMINATED`; this order's service window must not collide with another order's window on the same route, or it is rejected with `ERR_ROUTE_WINDOW_CONFLICT`; it must not collide with another order on the same machine inside the service buffer, or it is rejected with `ERR_ATM_SERVICE_LOCKOUT`; the drawing vault's on-hand `balance_cents` must be at least the `order_amount_cents`, or it is rejected with `ERR_VAULT_INSUFFICIENT`; and finally the `expected_vault_version` must match the vault's current `version`, or it is rejected with `ERR_STALE_VERSION`. The window, lockout, and insufficiency rules are detailed in §3.5.

When dispatch succeeds, several things happen together. The order's `vault_id` is set from the route's `vault_id`. The drawing vault has its `balance_cents` reduced by `order_amount_cents` and its `in_transit_cents` increased by the same amount, conserving the total, and its `version` is incremented by one — that increment is what makes any other client's stale `expected_vault_version` fail. On the cash dimension, the target machine moves to `AWAITING_LOAD`: a machine that was `EMPTY` or `LOW` transitions to `AWAITING_LOAD` when one of its orders dispatches.

### 3.5. Window Conflicts, Service Lockouts, and Vault Sufficiency

Two scheduling constraints protect the physical reality that a route can be in only one place at a time and a machine should not be serviced twice in quick succession. Both are evaluated only against **committed** orders — those in `DISPATCHED` or `LOADED` status. Orders still in `SCHEDULED` reserve nothing; a terminal order in `SETTLED` or `RECALLED` is likewise out of the picture.

The **route window conflict** rule treats each order's service window as a half-open interval running from its `service_window_start` up to but not including its `service_window_end`. When dispatching, the order being dispatched must not overlap the window of any other committed order on the same route. Two half-open intervals overlap when this order's start is strictly before the other's end and the other's start is strictly before this order's end. Intervals that merely touch — where one order's start equals another's end — do not overlap and are permitted; there is no buffer on the route. A violation is rejected with `ERR_ROUTE_WINDOW_CONFLICT`.

The **ATM service lockout** rule is stricter because it adds a buffer. It treats each order's window as a closed interval — including both endpoints — and expands that interval by thirty minutes on each side. When dispatching, the target machine must have no other committed order whose buffered closed interval intersects this order's closed interval. Because of the thirty-minute buffer on each side, two orders whose windows merely touch end-to-start do collide, and only a gap strictly greater than thirty minutes between them is allowed. A violation is rejected with `ERR_ATM_SERVICE_LOCKOUT`.

The **vault sufficiency** check is the fiscal guard: at dispatch the drawing vault's on-hand `balance_cents` must be greater than or equal to the `order_amount_cents`, otherwise the dispatch is rejected with `ERR_VAULT_INSUFFICIENT` and no cash moves.

### 3.6. Loading, Withdrawing, and Reconciling Cash

Once an order is dispatched and the truck arrives, a `FieldTech` performs **confirm-load**, advancing the order from `DISPATCHED` to `LOADED`. The only precondition beyond the order being dispatched is that the machine must not be `OUT_OF_SERVICE`; an attempt to load an out-of-service machine is rejected with `ERR_ATM_OUT_OF_SERVICE`. Notably, a `FAULTED` machine can still be loaded — only `OUT_OF_SERVICE` blocks it. The request may carry an optional `cassette_allocations` body describing how the loaded cash is split across the machine's cassettes. On success the cash leaves the in-transit bucket and enters the machine: the vault's `in_transit_cents` is reduced by `order_amount_cents` and its `in_machine_cents` is increased by the same amount. The machine's cassettes receive their `loaded_cents`, the machine's `loaded_cents` is recomputed as the sum of its cassettes' loaded cash, its `dispensed_cents_since_load` is reset to zero, and its `cash_status` moves to `LOADED`.

With cash in the cassettes, the machine takes **transactions**. A `FieldTech` or `PlatformAdmin` posts a transaction by naming its `kind` — either `WITHDRAWAL` or `BALANCE_INQUIRY` — and, for a withdrawal, an `amount_cents`. Only a `WITHDRAWAL` earns surcharge and interchange and actually dispenses cash; a `BALANCE_INQUIRY` does neither and carries an `amount_cents` of zero. A withdrawal's `amount_cents` must be a whole-number multiple of the machine's `note_denomination_cents`, or the post is rejected with `ERR_AMOUNT_NOT_DENOMINATED`. A live withdrawal also requires that the machine has an approved fee disclosure on file — its `fee_disclosure_id` must be set — and a withdrawal on a machine without one is rejected with `ERR_NO_FEE_DISCLOSURE`.

When a withdrawal posts, the system records a snapshot of the machine's `surcharge_cents` onto the transaction's own `surcharge_cents` (zero for a balance inquiry), assigns the transaction a monthly sequence number, and updates the running cash figures. The monthly sequence, `monthly_seq`, is the machine's current `monthly_wd_count` plus one — that is, the one-based position of this withdrawal among the machine's withdrawals this calendar month — and it pins the interchange tier this withdrawal will eventually settle at. After assigning it, the machine's `monthly_wd_count` is incremented by one. The withdrawal is charged to a cassette, recorded in the transaction's `cassette_id`: the system picks the cassette with the smallest position in the order `C1` before `C2` before `C3` before `C4` among those whose remaining cash — its `loaded_cents` minus its `dispensed_cents` — is at least the withdrawal amount; if no single cassette can cover the amount, it charges the smallest-position cassette that still has any positive remaining cash; and if no cassette has positive remaining cash, `cassette_id` is left null. A balance inquiry never charges a cassette and leaves `cassette_id` null. The charged cassette's `dispensed_cents` rises by the amount, and the machine's `dispensed_cents_since_load` rises by the amount. A `monthly_seq` is recorded only for withdrawals and is null for a balance inquiry.

A withdrawal can also trip the low-cash watermark. After a withdrawal posts on a machine whose `cash_status` is `LOADED`, the system checks whether the machine's remaining cash — its `loaded_cents` minus its `dispensed_cents_since_load` — has fallen to or below the low watermark of two million cents, that is, twenty thousand dollars. If it has, the machine's `cash_status` moves from `LOADED` to `LOW`. This transition fires only from `LOADED`; a withdrawal on an `EMPTY` or `AWAITING_LOAD` machine posts normally but does not change the cash dimension.

Reconciliation closes the loop. A `FieldTech` opens a **cash count** on a machine whose `cash_status` is either `LOADED` or `LOW`, which moves the machine to `RECONCILING`. The count carries the physically `counted_cents` the tech found in the machine and an optional `tolerance_cents`; when omitted, the acceptable variance defaults to five hundred cents. At the moment the count opens, the system computes the count's `expected_remaining_cents` as the machine's `loaded_cents` minus its `dispensed_cents_since_load`, and the `variance_cents` as the `counted_cents` minus that expected remaining. A negative variance means the machine is short; a positive variance means it is over. The count's `outcome` — and each affected cassette's `balance_status` — is `BALANCED` when the absolute value of the variance is less than or equal to the `tolerance_cents`, `OVER` when the variance is strictly greater than zero and beyond tolerance, and `SHORT` when it is strictly less than zero and beyond tolerance.

Finally, the `FieldTech` performs **close-out** on a machine that is `RECONCILING`, naming the machine and the cash count to close through its `cc_id` path identifier. Close-out reduces each cassette's `loaded_cents` to its expected remaining — its `loaded_cents` minus its `dispensed_cents` — and resets each cassette's `dispensed_cents` to zero, moves the machine's `cash_status` back to `EMPTY`, and cascades to the cash supply chain: the machine's currently `LOADED` replenishment order moves to its terminal `SETTLED` status, and the vault's `in_machine_cents` is reduced by that order's `order_amount_cents`. That decrement is the final leg of cash conservation: the cash that had been resident in the machine leaves the `in_machine_cents` bucket and returns to the vault's on-hand `balance_cents`, conserving `provisioned_cents` exactly as §2.7's formula (`balance_cents = provisioned_cents − in_transit_cents − in_machine_cents`) requires. A `SETTLED` order — like a `RECALLED` one — funds neither `in_transit_cents` nor `in_machine_cents`; the cash is reconciled out of the *machine* bucket, not destroyed.

### 3.7. Recalling an Order

Sometimes a scheduled or dispatched replenishment must be pulled back. A `VaultController` performs a **recall**, which is the compensation path of the order lifecycle. A recall from `SCHEDULED` simply moves the order to its terminal `RECALLED` status; because no vault cash was ever debited for a scheduled order, no vault adjustment is needed, though if the machine had moved to `AWAITING_LOAD` for this order its `cash_status` reverts to its prior value of `EMPTY` or `LOW`. A recall from `DISPATCHED` is the consequential one: it restores conservation by crediting the vault's `balance_cents` by `order_amount_cents` and reducing its `in_transit_cents` by the same amount, and it increments the vault's `version` by one — which is precisely why a recall can invalidate another client's in-flight `expected_vault_version`. The machine's `cash_status` reverts from `AWAITING_LOAD` back to `EMPTY` or `LOW`, and the order lands in `RECALLED`.

### 3.8. Jam and Fault Service Tickets

A machine breaks, jams, or loses its network link, and a **service ticket** captures the repair lifecycle on the operational dimension. A `FieldTech` or `PlatformAdmin` opens a ticket by naming the faulted machine's `atm_id`, a `fault_kind` of `CASH_JAM`, `CARD_READER`, `NETWORK`, or `DISPENSER`, and a `severity` of `MINOR` or `MAJOR`; when severity is omitted it defaults to `MINOR`. Opening a ticket immediately drives the machine's `operational_status`: a `MINOR` ticket forces the machine to `FAULTED`, while a `MAJOR` ticket forces it to `OUT_OF_SERVICE`. A major ticket opened on a machine already `FAULTED` escalates it onward to `OUT_OF_SERVICE`. None of this touches the cash dimension. A new ticket is born `OPEN`, with `reopen_count` zero and `assigned_tech_id` null.

The ticket then cycles. A `FieldTech` **acknowledges** an `OPEN` ticket, moving it to `ACKNOWLEDGED` and recording the acting tech's `X-User-ID` as the ticket's `assigned_tech_id`. The same tech then **resolves** an `ACKNOWLEDGED` ticket, moving it to `RESOLVED`; resolution requires that the acting tech is the recorded `assigned_tech_id`, and an attempt by anyone else is rejected with `ERR_NOT_TICKET_OWNER`. When a ticket resolves, the system checks whether any other ticket on the same machine remains `OPEN` or `ACKNOWLEDGED`; if none does, the machine's `operational_status` returns to `IN_SERVICE`. Because tickets are cyclic, a `RESOLVED` ticket can be **reopened** back to `OPEN`, which increments its `reopen_count` by one and re-faults the machine — to `FAULTED` for a minor ticket or `OUT_OF_SERVICE` for a major one. A ticket that is `OPEN` or `ACKNOWLEDGED` can instead be **cancelled** to its terminal `CANCELLED` status; like resolution, cancellation returns the machine to `IN_SERVICE` if no other `OPEN` or `ACKNOWLEDGED` ticket on that machine remains. Tickets can be listed and filtered by `atm_id` and by `status`.

### 3.9. Fee Disclosure and the Compliance Gate

Before a machine can take live withdrawals, a `ComplianceOfficer` (or a `PlatformAdmin`) must draft and a `ComplianceOfficer` must approve a **fee disclosure**. A draft is created against a machine by supplying the `disclosed_surcharge_cents` printed on the on-screen and on-machine notice and an `ack_text_present` flag stating whether the mandatory consumer acknowledgement text is present; the flag defaults to false. At draft time the system snapshots the machine's location `jurisdiction_code` onto the disclosure and computes the `regulatory_cap_cents` from it: the cap is 300 cents in `CA`, 500 cents in `NY`, 275 cents in `TX`, and 300 cents in `FL`. A new disclosure is born `DRAFT`. Disclosures for a machine can be listed and filtered by `status`.

A `ComplianceOfficer` **approves** a draft, moving it from `DRAFT` to `APPROVED`. Approval enforces three checks. The `disclosed_surcharge_cents` must equal the machine's current `surcharge_cents`, or approval is rejected with `ERR_DISCLOSURE_MISMATCH`. The `disclosed_surcharge_cents` must be less than or equal to the `regulatory_cap_cents` for the jurisdiction, or it is rejected with `ERR_SURCHARGE_CAP_EXCEEDED`. And `ack_text_present` must be true, or it is rejected with `ERR_ACK_TEXT_MISSING`. When all three hold, the disclosure becomes `APPROVED`, any previously `APPROVED` disclosure on the same machine is superseded and moved to `REJECTED`, and the machine's `fee_disclosure_id` is set to this disclosure — the act that arms the machine for live revenue. A `ComplianceOfficer` may also **reject** a `DRAFT` disclosure outright, moving it to its terminal `REJECTED` status. The approved disclosure is what the withdrawal gate in §3.6 and the settlement gate in §3.10 both look for; without one, those operations fail with `ERR_NO_FEE_DISCLOSURE`.

### 3.10. Settlement and Revenue Computation

Revenue is realized in a **settlement run**. A `SettlementOfficer` creates a run by naming the `atm_id` to settle and a settlement window bounded by `window_start` (inclusive) and `window_end` (exclusive) as ISO 8601 UTC instants. A new run is born `DRAFT`. The officer then **settles** it, moving it from `DRAFT` to its terminal, immutable `SETTLED` status. Settlement is gated by two preconditions: the machine must have an approved fee disclosure, or settlement is rejected with `ERR_NO_FEE_DISCLOSURE`; and none of the withdrawals the run is about to sweep may already be bound to another settlement run, or it is rejected with `ERR_TXN_ALREADY_SETTLED`.

Settling sweeps every `WITHDRAWAL` transaction on the run's machine whose creation time falls in the half-open window from `window_start` up to but not including `window_end` and whose `settlement_run_id` is still null — balance inquiries are never swept. From that swept set the run computes its figures. The `withdrawal_count` is the number of swept withdrawals. The `surcharge_revenue_cents` is the sum of each swept withdrawal's snapshotted `surcharge_cents`. The `interchange_revenue_cents` is the sum, over each swept withdrawal, of an interchange rate selected marginally by that withdrawal's own `monthly_seq`: a withdrawal whose `monthly_seq` is from 1 through 500 earns 35 cents, one whose `monthly_seq` is from 501 through 2000 earns 42 cents, and one whose `monthly_seq` is 2001 or higher earns 50 cents. The `network_fee_cents` is a flat network charge of 8 cents per swept withdrawal — that is, 8 cents multiplied by the `withdrawal_count` — and it is subtracted from revenue. The `net_operator_revenue_cents` is therefore the `surcharge_revenue_cents` plus the `interchange_revenue_cents` minus the `network_fee_cents`. All of these are exact integer cents; nothing is rounded because every term is an integer sum. As the run settles, every swept transaction has its `settlement_run_id` bound to this run, which is what protects it from being double-counted by a later run.

### 3.11. The Commission Split

Settling a run does not stop at the operator's books — it cascades to generate a **commission statement** for the host merchant, born `ACCRUED`. The statement names the `settlement_run_id` it derives from, and the system resolves the `site_merchant_id` from the run's machine through its location. The split is computed in a pinned order, because the ceiling cap depends on what came before.

First, with the run's `net_operator_revenue_cents` already known from §3.10, the system computes two candidate amounts. The percentage candidate, `pct_amount_cents`, is the `net_operator_revenue_cents` multiplied by the merchant's `commission_pct_bps`, divided by 10000, with the fractional part discarded (floored). The flat candidate, `flat_amount_cents`, is the merchant's `commission_flat_per_wd_cents` multiplied by the run's `withdrawal_count`. Second, the system selects a base according to the merchant's `commission_basis`: under `GREATER_OF` the base is the larger of `pct_amount_cents` and `flat_amount_cents`; under `PCT_ONLY` the base is `pct_amount_cents` and the flat candidate is ignored even when it would be larger; under `FLAT_ONLY` the base is `flat_amount_cents`.

Third comes the monthly ceiling cap, and this is where evaluation order matters. The system sums the `commission_cents` of every commission statement for this merchant that is currently `ACCRUED` or `PAID` and whose `created_at` falls in the same calendar month as this new statement's `created_at`, excluding any `VOIDED` statement and excluding this statement itself — this is the merchant's month-to-date commission. The "same calendar month" is keyed on the statement's creation instant under the logical clock, not on the settlement window, so two statements generated in the same clock month share one ceiling no matter what windows they swept. The remaining headroom is the merchant's `commission_monthly_ceiling_cents` minus that month-to-date total, but never less than zero. The statement's `commission_cents` is then the smaller of the selected base and the remaining headroom — except that a merchant whose `payout_status` is `SUSPENDED` accrues a `commission_cents` of exactly zero regardless. Finally, `operator_keeps_cents` is the run's `net_operator_revenue_cents` minus the statement's `commission_cents`.

A `SettlementOfficer` later **pays** an `ACCRUED` statement, moving it to its terminal `PAID` status; payment requires the merchant's `payout_status` to be `ACTIVE`, and an attempt to pay a statement whose merchant is suspended is rejected with `ERR_MERCHANT_SUSPENDED`. Alternatively the officer **voids** an `ACCRUED` statement, moving it to its terminal `VOIDED` status; voiding frees ceiling headroom by removing that statement's `commission_cents` from the merchant's month-to-date commission, so a subsequent statement in the same month sees more remaining headroom. Statements can be listed and filtered by `settlement_run_id` or `site_merchant_id`.

### 3.12. The Logical Clock and Test Seeding

The server runs on a logical clock rather than wall time, and that clock drives every window comparison, forecast window, and month-rollover rule deterministically. The clock starts at 2026-01-01T00:00:00Z; until it is explicitly set it reads exactly that default and never falls back to wall-clock time. A `PlatformAdmin` advances it by supplying a `to_iso8601` instant, and the response reports the new `current_utc`. Advancing the clock across a calendar-month boundary recomputes each machine's `monthly_wd_count`, resetting the cumulative monthly withdrawal count to zero at the rollover so that the interchange tier restarts each month.

Because the interchange tiers turn over at high monthly-sequence boundaries — the first tier ends at the five-hundredth withdrawal of the month — a test-driving seeder lets a `PlatformAdmin` set a machine's current-month cumulative withdrawal count directly by supplying the machine's `atm_id` and the desired `monthly_wd_count`. This sets only the machine's `monthly_wd_count` and touches no other field and creates no transaction rows; the next withdrawal posted then receives a `monthly_seq` of that seeded count plus one.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource or add a new resource to a collection return a `201 Created` status code. Operations that modify an existing resource — including the state-transition actions and the configuration toggles — return a `200 OK` status code. The request and response payloads for each operation, including which fields are required and which side effects fire, are described in the §3 narratives above; the table below is a routing summary only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/site-merchants` | Create a site-merchant commission contract | PlatformAdmin |
| GET | `/site-merchants/{id}` | Read a site merchant | PlatformAdmin, SettlementOfficer |
| POST | `/site-merchants/{id}/suspend` | Suspend a merchant's payout | PlatformAdmin |
| POST | `/vaults` | Create a cash vault with a provisioned baseline | PlatformAdmin |
| GET | `/vaults/{id}` | Read a vault including derived balances and version | PlatformAdmin, VaultController |
| POST | `/routes` | Create an armored route bound to a vault | PlatformAdmin |
| POST | `/routes/{id}/pause` | Pause an armored route | PlatformAdmin, VaultController |
| GET | `/routes/{id}` | Read an armored route | PlatformAdmin, VaultController |
| GET | `/routes` | List armored routes; filter by vault_id | PlatformAdmin, VaultController |
| POST | `/locations` | Create a host site, bound to a merchant and route | PlatformAdmin |
| GET | `/locations/{id}` | Read a location | PlatformAdmin, SettlementOfficer |
| GET | `/locations` | List locations; filter by site_merchant_id or route_id | PlatformAdmin, SettlementOfficer |
| POST | `/atms` | Provision an ATM at a location | PlatformAdmin |
| GET | `/atms/{id}` | Read an ATM with all computed fields | PlatformAdmin, FieldTech, SettlementOfficer, VaultController, ComplianceOfficer |
| GET | `/atms` | List ATMs; filter by location_id or fee_disclosure_id | PlatformAdmin, FieldTech, SettlementOfficer |
| GET | `/atms/{id}/forecast` | Compute the cash-load forecast under the chosen variant | PlatformAdmin, VaultController, FieldTech |
| POST | `/atms/{id}/cassettes` | Add a cassette slot to an ATM | PlatformAdmin, FieldTech |
| GET | `/atms/{id}/cassettes` | List cassettes for an ATM | PlatformAdmin, FieldTech, SettlementOfficer |
| POST | `/atms/{id}/transactions` | Post a WITHDRAWAL or BALANCE_INQUIRY to the ATM | PlatformAdmin, FieldTech |
| GET | `/atms/{id}/transactions` | List transactions for an ATM; filter by kind | PlatformAdmin, FieldTech, SettlementOfficer |
| GET | `/transactions/{id}` | Read a single transaction | PlatformAdmin, FieldTech, SettlementOfficer |
| GET | `/transactions` | List transactions; filter by atm_id, cassette_id, settlement_run_id, or kind | PlatformAdmin, FieldTech, SettlementOfficer |
| POST | `/replenishment-orders` | Schedule a replenishment order | VaultController, PlatformAdmin |
| GET | `/replenishment-orders/{id}` | Read a replenishment order | PlatformAdmin, VaultController, FieldTech |
| GET | `/replenishment-orders` | List replenishment orders; filter by atm_id, route_id, or vault_id | PlatformAdmin, VaultController, FieldTech |
| POST | `/replenishment-orders/{id}/dispatch` | Dispatch an order (OCC-checked vault debit) | VaultController |
| POST | `/replenishment-orders/{id}/confirm-load` | Confirm cash loaded into the machine | FieldTech |
| POST | `/replenishment-orders/{id}/recall` | Recall an order; compensates the vault | VaultController |
| POST | `/atms/{id}/cash-counts` | Open a cash count and compute variance | FieldTech |
| GET | `/atms/{id}/cash-counts` | List cash counts for an ATM | PlatformAdmin, FieldTech, SettlementOfficer |
| POST | `/atms/{id}/cash-counts/{cc_id}/close-out` | Close reconciliation; settle the loaded order | FieldTech |
| POST | `/service-tickets` | Open a jam/fault ticket | FieldTech, PlatformAdmin |
| GET | `/service-tickets/{id}` | Read a service ticket | PlatformAdmin, FieldTech |
| GET | `/service-tickets` | List service tickets; filter by atm_id or status | PlatformAdmin, FieldTech |
| POST | `/service-tickets/{id}/acknowledge` | Acknowledge a ticket; record assigned_tech_id | FieldTech |
| POST | `/service-tickets/{id}/resolve` | Resolve a ticket; restore the ATM if last open | FieldTech |
| POST | `/service-tickets/{id}/reopen` | Reopen a resolved ticket; re-fault the ATM | FieldTech |
| POST | `/service-tickets/{id}/cancel` | Cancel a ticket; restore the ATM if last open | FieldTech |
| POST | `/atms/{id}/fee-disclosures` | Draft a fee disclosure for an ATM | ComplianceOfficer, PlatformAdmin |
| GET | `/atms/{id}/fee-disclosures` | List fee disclosures for an ATM; filter by status | PlatformAdmin, ComplianceOfficer, SettlementOfficer |
| POST | `/fee-disclosures/{id}/approve` | Approve a disclosure; supersede prior; arm the ATM | ComplianceOfficer |
| POST | `/fee-disclosures/{id}/reject` | Reject a draft disclosure | ComplianceOfficer |
| POST | `/settlement-runs` | Create a DRAFT settlement run for an ATM | SettlementOfficer |
| GET | `/settlement-runs/{id}` | Read a settlement run with computed revenue fields | PlatformAdmin, SettlementOfficer |
| GET | `/settlement-runs` | List settlement runs; filter by atm_id | PlatformAdmin, SettlementOfficer |
| POST | `/settlement-runs/{id}/settle` | Settle a run; sweep withdrawals; cascade a commission statement | SettlementOfficer |
| GET | `/commission-statements/{id}` | Read a commission statement | PlatformAdmin, SettlementOfficer |
| GET | `/commission-statements` | List commission statements; filter by settlement_run_id or site_merchant_id | PlatformAdmin, SettlementOfficer |
| POST | `/commission-statements/{id}/pay` | Pay a commission statement; requires merchant ACTIVE | SettlementOfficer |
| POST | `/commission-statements/{id}/void` | Void a commission statement; free ceiling headroom | SettlementOfficer |
| POST | `/_clock/set_current_utc` | Set the server logical clock | PlatformAdmin |
| POST | `/_inject/atm_monthly_wd_count` | Seed an ATM's current-month withdrawal count (test-driving) | PlatformAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 422 |
| `ERR_DUPLICATE_SERIAL` | 409 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_NOT_TICKET_OWNER` | 403 |
| `ERR_SURCHARGE_CAP_EXCEEDED` | 422 |
| `ERR_ACK_TEXT_MISSING` | 422 |
| `ERR_DISCLOSURE_MISMATCH` | 422 |
| `ERR_NO_FEE_DISCLOSURE` | 422 |
| `ERR_ATM_OUT_OF_SERVICE` | 409 |
| `ERR_ROUTE_PAUSED` | 409 |
| `ERR_AMOUNT_NOT_DENOMINATED` | 422 |
| `ERR_ROUTE_WINDOW_CONFLICT` | 409 |
| `ERR_ATM_SERVICE_LOCKOUT` | 409 |
| `ERR_VAULT_INSUFFICIENT` | 422 |
| `ERR_TXN_ALREADY_SETTLED` | 409 |
| `ERR_MERCHANT_SUSPENDED` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_VALIDATION` | 422 |
