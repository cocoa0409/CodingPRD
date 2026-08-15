# CNG Station Ops API — Product Requirements Document

## 1. Introduction

A network operator in the mold of Clean Energy Fuels runs a portfolio of compressed natural gas (CNG) and renewable natural gas (RNG) fueling stations. Some lanes serve the retail public; others serve contracted fleet accounts whose drivers fuel against pre-authorized cards; many stations serve both. Behind every fill sit operational concerns that make or break the business: compressors degrade and go offline, dispenser meters drift and must be recalibrated on a fixed cadence, maintenance has to be scheduled without stranding customers, safety inspections carry hard regulatory consequences, and both governments and fleet customers expect precise gallon-equivalent accounting for tax credits and minimum-volume contracts.

This document specifies the API that backs those operations. The system tracks station equipment health and derives a station-level uptime posture that gates all fueling; it authorizes and settles fueling sessions for both walk-up retail customers and card-carrying fleet drivers; it manages pricing policies with optional volume tiers and supply contracts with shortfall penalties; it schedules maintenance windows against backup fueling capacity; it enforces safety-inspection discipline with strict segregation of duties; and it computes fuel tax credit claims from settled dispensing history. All business resources are mounted under the `/cng` prefix, and a single administrative capability outside that prefix drives the server's logical clock, on which every time-based obligation — calibration due dates, hold timeouts, month-close settlement, window expiry — ultimately depends.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request carries two headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, naming exactly one of the six declared roles. A request missing either header, or whose role value is not one of the declared role names, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). A request whose role is valid but not permitted for the target endpoint is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

The six roles are spelled exactly as follows: `NetworkOperator`, `StationManager`, `ComplianceOfficer`, `FleetAccountManager`, `FleetDriver`, and `Anonymous`.

A `NetworkOperator` is the network-level central-ops principal: it creates and lifecycle-manages stations, pricing policies, fleet accounts, and supply contracts, decides submitted tax credit claims, and exclusively drives the logical clock. When `X-User-Role` is `NetworkOperator`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server never compares it to any resource's `id`.

A `StationManager` runs one or more stations day to day: registering compressors and dispensers, reporting compressor conditions, recording calibrations, scheduling and executing maintenance windows, arranging and drawing on backup fueling, performing safety inspections, and drafting and finalizing tax credit claims. When `X-User-Role` is `StationManager`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server records it where a workflow calls for it — for example as `performed_by` on a safety inspection — but does not compare it to any entity's `id`.

A `ComplianceOfficer` is the compliance reviewer: approving completed safety inspections (never ones they performed) and submitting finalized tax credit claims. When `X-User-Role` is `ComplianceOfficer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server records it as `approved_by` when an inspection is approved but does not compare it to any entity's `id`.

A `FleetAccountManager` is the fleet-side account administrator. When `X-User-Role` is `FleetAccountManager`, `X-User-ID` is the `id` of the acting `FleetAccount`; ownership checks on any resource that references a `FleetAccount` compare the resource's `fleet_account_id` field to `X-User-ID`, and a mismatch is rejected with `ERR_ACCOUNT_OWNERSHIP_MISMATCH` (HTTP 403).

A `FleetDriver` is a card-carrying driver. When `X-User-Role` is `FleetDriver`, `X-User-ID` is the `id` of the acting `FleetCard`; ownership checks compare the referenced or session-resident card identifier to `X-User-ID`, and a mismatch is rejected with `ERR_CARD_OWNERSHIP_MISMATCH` (HTTP 403).

An `Anonymous` principal is an unauthenticated retail customer at a public dispenser. When `X-User-Role` is `Anonymous`, `X-User-ID` is an opaque pump-side identifier not tied to any persisted entity, and the server does not compare it to any entity's `id`.

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

List endpoints accept two query parameters. `limit` controls page size: it defaults to 10, with a minimum of 1 and a maximum of 100. `offset` controls how many records to skip and defaults to 0. List responses carry the pagination fields `limit`, `offset`, `total_count`, and `has_more` in the `meta` object. Unless a filter says otherwise, list results are sorted by `created_at` in ascending order, oldest first.

### 2.4. Resource Identity, Timestamps, and Versioning

Every persisted resource carries an `id` that is a server-minted UUID with no type prefix. Alongside it, resources carry `created_at` and `updated_at` timestamps formatted as ISO 8601 UTC with three fractional digits, and a `version` integer that starts at 1 when the resource is created and increments by exactly one on every mutation, including system-driven mutations such as clock sweeps and cascades. Two resource types are deliberately thinner: a calibration record and a monthly settlement are immutable once created, so each carries only `id` and `created_at` — both `updated_at` and `version` are absent from them. Consistency is immediate: every mutation is fully reflected in the response of the request that caused it.

### 2.5. The Logical Clock and Epoch Sweeps

The server runs on a logical clock, never the wall clock. At startup the logical time is exactly 2026-08-01T00:00:00Z. A `NetworkOperator` may advance the logical clock through the test-driving capability `POST /_clock/set_current_utc`, supplying the target instant as `to_iso8601`; the response echoes the new logical time as `current_utc` and reports the number of sweeps applied as `sweeps_applied`.

Setting the clock runs the full epoch sweep, which applies the following time-based transitions, each affected entity having its `version` incremented by one:

1. **Hold timeouts.** Any fueling session that has remained AUTHORIZED for thirty minutes since its `authorized_at` timestamp is voided with `void_reason` TIMEOUT, releasing any hold it carried.
2. **Calibration due dates.** Any IN_SERVICE dispenser whose `calibration_due_at` has passed moves to CALIBRATION_HOLD.
3. **Pricing policy expiry.** Any ACTIVE pricing policy whose `effective_to` has passed moves to EXPIRED.
4. **Window lapse.** Any maintenance window still SCHEDULED once its `ends_at` has passed moves to LAPSED.
5. **Backup expiry.** Any backup fueling arrangement in RESERVED or ACTIVATED status whose `available_until` has passed moves to EXPIRED, freezing its accumulated usage.
6. **Inspection overdue.** Any SCHEDULED safety inspection whose `scheduled_for` has passed moves to OVERDUE.
7. **Contract expiry.** Any ACTIVE supply contract whose `end_month` is strictly earlier than the current calendar month moves to EXPIRED.
8. **Daily usage rollover.** Any fleet card whose `current_day_date` is earlier than the current UTC date has its `current_day_gge` reset to zero and its `current_day_date` set to the current date.
9. **Month-close settlement.** Any COMPLETED fueling session whose `completed_at` month is strictly earlier than the current calendar month moves to SETTLED and is stamped with `settled_at`.

### 2.6. Units, Precision, and Rounding

All fuel volumes are expressed in gasoline-gallon-equivalents (GGE). The conversion constant for CNG is 2.567 kilograms per GGE: dividing a metered mass in kilograms by 2.567 yields the uncorrected GGE volume. Every GGE quantity the system computes — session volumes, daily card usage, settlement volumes, claim volumes — is rounded half-up to three decimal places, where "half-up" means a discarded fraction of exactly one-half rounds away from zero.

Money is always integer cents. Hold amounts, billed totals, claim amounts, and settlement penalties are rounded half-up to a whole cent where a multiplication produces a fraction. Unit prices, credit limits, balances, and penalty rates are integers and require no rounding.

A calibration record's `measured_error_pct` is a signed percentage carried to two decimal places, where a positive value indicates the meter over-delivers relative to the true mass. A dispenser's `correction_factor` (and a calibration record's `applied_correction_factor`) is carried to four decimal places. Backup commitment figures (`committed_gge`, `backup_capacity_gge`) are integers. All datetime comparisons run in UTC.

### 2.7. Station Uptime Posture and the Outage Void Cascade

Every station carries a derived `uptime_posture` of OPERATIONAL, DEGRADED, or OUTAGE that gates whether fueling may be authorized at all. The posture is recomputed whenever a compressor's condition changes, whenever a dispenser's status changes, whenever equipment is created, and whenever a station is activated. The derivation is a pure aggregate over the station's equipment, insensitive to the order in which equipment records changed:

- Count the station's compressors whose condition is ONLINE or DEGRADED, and count its dispensers whose status is IN_SERVICE. If either count is zero, the posture is OUTAGE.
- Otherwise, if any compressor is DEGRADED or any dispenser is on CALIBRATION_HOLD, the posture is DEGRADED.
- Otherwise the posture is OPERATIONAL.

A newly created station has no equipment and therefore starts in OUTAGE posture (and SETUP status) until compressors and dispensers are registered.

Whenever a recompute changes a station's posture to OUTAGE, a void cascade fires: every AUTHORIZED fueling session at that station is voided with `void_reason` STATION_OUTAGE, processed in `created_at` ascending order, and each affected private session releases its hold — the account's `outstanding_balance_cents` decreases by the session's `hold_amount_cents` and the account's `version` increments by one per session. New authorization attempts at a station whose posture is OUTAGE are rejected with `ERR_STATION_OUTAGE` (HTTP 409).

### 2.8. Validation Pipeline and Error Precedence

Every request travels through a fixed ten-stage validation pipeline. The stages run in the order given below, and when several checks would fail, the caller receives the error produced by the earliest applicable stage — later failures are masked, never reported alongside.

1. **Header presence and validity.** `X-User-ID` and `X-User-Role` must be present and the role must be one of the six declared names, else `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400).
2. **Role permission.** The caller's role must be listed for the endpoint, else `ERR_FORBIDDEN_ROLE` (HTTP 403). This stage also covers a PUBLIC session being completed by any role other than `Anonymous`.
3. **Request shape.** Required fields must be present, enum values must be valid, numeric constraints must be honored (inputs required to be positive — such as `estimated_gge`, `metered_mass_kg`, `capacity_scf_per_minute`, `price_per_gge_cents`, `credit_limit_cents`, `daily_gge_limit`, `committed_monthly_gge`, `contract_price_per_gge_cents`, `backup_capacity_gge`, and `committed_gge` — must be greater than zero), month strings must be well-formed YYYY-MM values, tier fields may appear only on PRIVATE pricing policies and then only as a both-or-neither pair, and `fleet_card_id` must not be sent to the public authorization entry point. Violations are `ERR_INVALID_REQUEST` (HTTP 400).
4. **Resource existence.** Path identifiers are validated left to right, then body foreign keys such as `dispenser_id`, `fleet_card_id`, `station_id`, `fleet_account_id`, and `compressor_id`. Each missing resource yields its own error: `ERR_STATION_NOT_FOUND`, `ERR_COMPRESSOR_NOT_FOUND`, `ERR_DISPENSER_NOT_FOUND`, `ERR_CALIBRATION_RECORD_NOT_FOUND`, `ERR_PRICING_POLICY_NOT_FOUND`, `ERR_FLEET_ACCOUNT_NOT_FOUND`, `ERR_FLEET_CARD_NOT_FOUND`, `ERR_SUPPLY_CONTRACT_NOT_FOUND`, `ERR_MONTHLY_SETTLEMENT_NOT_FOUND`, `ERR_SESSION_NOT_FOUND`, `ERR_MAINTENANCE_WINDOW_NOT_FOUND`, `ERR_BACKUP_ARRANGEMENT_NOT_FOUND`, `ERR_INSPECTION_NOT_FOUND`, or `ERR_TAX_CLAIM_NOT_FOUND` (all HTTP 404).
5. **Entity-backed ownership.** A `FleetDriver`'s `X-User-ID` must equal the referenced `fleet_card_id` — and, on completion or void, the session's card — else `ERR_CARD_OWNERSHIP_MISMATCH` (HTTP 403); a `FleetAccountManager`'s `X-User-ID` must equal the referenced `fleet_account_id`, else `ERR_ACCOUNT_OWNERSHIP_MISMATCH` (HTTP 403).
6. **State preconditions.** The station must be ACTIVE where required; the dispenser must be IN_SERVICE at authorization; the card and account must be ACTIVE where required; sessions, windows, backups, inspections, claims, and contracts must sit in the transition's required from-state; and the OCC field `expected_station_version` or `expected_fleet_account_version` must equal the parent's current `version`. Failures yield the state-specific errors (HTTP 409) or the stale-version errors `ERR_STALE_STATION_VERSION` and `ERR_STALE_ACCOUNT_VERSION` (HTTP 412).
7. **Safety gates.** Authorization is refused while a station's posture is OUTAGE (`ERR_STATION_OUTAGE`, HTTP 409); claim submission, station resume, and non-EMERGENCY window creation are refused while the station has an OVERDUE inspection (`ERR_OVERDUE_INSPECTION`, HTTP 409); an inspection approver must differ from its performer (`ERR_SEGREGATION_OF_DUTIES`, HTTP 403); and starting a window that would remove the station's last online compression capacity without covering backup is refused (`ERR_BACKUP_REQUIRED`, HTTP 409).
8. **Uniqueness, overlap, and idempotency.** Card numbers must be unique (`ERR_CARD_NUMBER_EXISTS`), maintenance windows must respect overlap and turnaround rules (`ERR_WINDOW_OVERLAP`), backup capacity must fit (`ERR_BACKUP_CAPACITY_EXCEEDED`), a `client_ref` may not be reused at a station by a different card or access type (`ERR_DUPLICATE_CLIENT_REF`), a contract month may be settled only once (`ERR_MONTH_ALREADY_SETTLED`), a claim period may not overlap a SUBMITTED or APPROVED claim at the same station (`ERR_CLAIM_PERIOD_OVERLAP`), only one ACTIVE contract may cover an account-station pair (`ERR_CONTRACT_ALREADY_ACTIVE`), and the station's access mode must serve the requested session type (`ERR_ACCESS_MODE_MISMATCH`) — all HTTP 409.
9. **Temporal validity.** Start must precede end on window, policy, backup, and claim time ranges, and `end_month` must not precede `start_month` (`ERR_INVALID_TIME_RANGE`, HTTP 422); a window may start only inside its own time range (`ERR_WINDOW_NOT_IN_TIME_RANGE`, HTTP 409); a backup may be activated only inside its availability (`ERR_BACKUP_NOT_IN_WINDOW`, HTTP 409); and a month may be settled only if it is strictly before the current logical month (`ERR_MONTH_NOT_CLOSED`, HTTP 409) and within the contract's span (`ERR_MONTH_OUT_OF_CONTRACT`, HTTP 409).
10. **Fiscal gates, last.** Credit limit (`ERR_CREDIT_LIMIT_EXCEEDED`, HTTP 402), daily card GGE limit (`ERR_DAILY_LIMIT_EXCEEDED`, HTTP 409), resolvable unit price (`ERR_NO_ACTIVE_PRICE`, HTTP 422), zero-balance requirement on account close (`ERR_OUTSTANDING_BALANCE_NONZERO`, HTTP 409), non-empty eligible set on claim finalize (`ERR_NO_ELIGIBLE_VOLUME`, HTTP 422), and backup draw within commitment (`ERR_BACKUP_DRAW_EXCEEDED`, HTTP 409).

The ordering matters in practice. During private authorization, for example, a stale `expected_fleet_account_version` surfaces as `ERR_STALE_ACCOUNT_VERSION` at stage six, long before the credit check at stage ten is consulted; a `client_ref` collision at stage eight is reported before an inverted claim period at stage nine would be; and on pricing-policy creation a malformed tier payload at stage three masks every downstream failure.

### 2.9. Optimistic Concurrency Control

Two write endpoints are guarded by optimistic concurrency control, and no other endpoint takes a version field.

Creating a pricing policy through `POST /cng/pricing-policies` requires the request to carry `expected_station_version`, holding the client's last observed `version` of the station the policy is being created against. If the station's current `version` has advanced beyond what the client observed — because activation, suspension, resumption, or a prior policy creation moved it — the create is rejected with `ERR_STALE_STATION_VERSION` (HTTP 412). Policy creation legitimately supersedes the prior ACTIVE policy with the same station, scope, and fuel key, so a writer holding a stale station view must not supersede on the basis of outdated state.

Authorizing a private fueling session through `POST /cng/fueling-sessions/authorize` requires the request to carry `expected_fleet_account_version`, holding the client's last observed `version` of the card's fleet account. If the account's current `version` no longer matches, the authorization is rejected with `ERR_STALE_ACCOUNT_VERSION` (HTTP 412). Multiple holds against one account are legitimate, so a writer holding a stale account view must not post a hold on the basis of an outdated balance.

Endpoints not named above accept no version field at all.

### 2.10. Data Visibility and Ownership Scoping

Read access follows the role. `NetworkOperator`, `StationManager`, and `ComplianceOfficer` read without scoping wherever an endpoint lists them. `FleetAccountManager` views are auto-scoped to the account identified by their `X-User-ID`: account lists and details, fleet cards, fueling sessions, supply contracts, and monthly settlements are all filtered to that account. `FleetDriver` views are scoped to their own card, that card's sessions, and their own account. Requesting a detail resource outside the caller's scope is rejected with `ERR_ACCOUNT_OWNERSHIP_MISMATCH` or `ERR_CARD_OWNERSHIP_MISMATCH` (HTTP 403) as applicable. `Anonymous` holds no read access to any list or detail endpoint.

## 3. Business Logic & Workflows

### 3.1. Station Onboarding, Equipment, and Operational Status

A `NetworkOperator` opens a new station by supplying a human-readable `station_name`, a `station_code` that must be unique across all stations, an `access_mode` of PUBLIC, PRIVATE, or DUAL declaring which session access types the station serves, and a `backup_capacity_gge` — a positive integer capping the aggregate committed backup volume the station may hold across overlapping arrangements. The station is born in SETUP status with `uptime_posture` OUTAGE and `version` 1, and it cannot fuel anyone until it is equipped and activated.

Equipment registration falls to a `StationManager`. A compressor is registered with its owning `station_id`, a `compressor_code` unique within that station, and a positive `capacity_scf_per_minute` rating; it starts ONLINE. A dispenser is registered with its owning `station_id`, a `dispenser_code` unique within that station, and a `fuel_type` of CNG or RNG; it starts IN_SERVICE with `correction_factor` 1.0, `last_calibration_at` set to the logical-clock creation time, and `calibration_due_at` set ninety days later. Every equipment creation triggers a recompute of the owning station's uptime posture as described in §2.7. Compressor and dispenser collections can be listed with optional filters — compressors by `station_id` and `condition`, dispensers by `station_id`, `status`, and `fuel_type` — and stations by `status`.

Activation by a `NetworkOperator` moves a station from SETUP to ACTIVE. The station must still be in SETUP, else `ERR_STATION_NOT_IN_SETUP` (HTTP 409), and it must have at least one compressor and at least one dispenser registered, else `ERR_STATION_NOT_EQUIPPED` (HTTP 409). Activation increments the station's `version` by one and recomputes the posture, which with fresh ONLINE and IN_SERVICE equipment typically lands on OPERATIONAL.

Suspension moves a station from ACTIVE to SUSPENDED; attempting it on a station that is not ACTIVE yields `ERR_STATION_NOT_ACTIVE` (HTTP 409). A manual suspension by a `NetworkOperator` voids every AUTHORIZED fueling session at the station with `void_reason` MANAGER_VOID, releasing each private session's hold (the account balance decreases by `hold_amount_cents` and the account `version` increments per session), and the station's `version` increments by one. Resumption returns a SUSPENDED station to ACTIVE; it requires the station to be SUSPENDED, else `ERR_STATION_NOT_SUSPENDED` (HTTP 409), and it is refused while any safety inspection at the station is OVERDUE, surfacing `ERR_OVERDUE_INSPECTION` (HTTP 409).

Once equipment is live, a `StationManager` reports compressor condition changes. From ONLINE a compressor may be reported DEGRADED or OFFLINE; from DEGRADED it may be reported back ONLINE or further OFFLINE; from OFFLINE it may be reported back ONLINE. Each report names the target `condition`, increments the compressor's `version`, and recomputes the station posture — reporting the last healthy compressor OFFLINE can tip the station into OUTAGE and fire the void cascade of §2.7. No condition report is accepted while a compressor is UNDER_MAINTENANCE: the attempt fails with `ERR_COMPRESSOR_UNDER_MAINTENANCE` (HTTP 409). Maintenance itself moves a compressor into and out of UNDER_MAINTENANCE without any manual report, as §3.6 describes.

### 3.2. Pricing Policies and Rate Windows

Prices are set per station, per access scope, and per fuel. A `NetworkOperator` creates a pricing policy with `station_id`, an `access_scope` of PUBLIC or PRIVATE, a `fuel_type` of CNG or RNG, a positive integer `price_per_gge_cents`, and an effectiveness window whose `effective_from` is inclusive and whose `effective_to` is exclusive and must be strictly later, else `ERR_INVALID_TIME_RANGE` (HTTP 422). The station must be ACTIVE, else `ERR_STATION_NOT_ACTIVE` (HTTP 409), and the request must carry `expected_station_version` per the OCC rule in §2.9.

A new policy is born ACTIVE. If an ACTIVE policy already exists with the same station, scope, and fuel key, that prior policy is immediately SUPERSEDED and its `version` increments by one, so at most one ACTIVE policy ever exists for a given key; creation also increments the station's `version` by one. When the logical clock passes a policy's `effective_to`, the epoch sweep moves it to EXPIRED. SUPERSEDED and EXPIRED are terminal.

PRIVATE policies may additionally carry a volume tier: `tier_threshold_gge` marks the account's station month-to-date volume at or above which `tier_price_cents` — a positive integer when present — replaces the base price. The two tier fields are both-or-neither and are forbidden on PUBLIC policies; violating either rule is `ERR_INVALID_REQUEST` (HTTP 400). Policy collections support filtering by `station_id`, `access_scope`, and `status`. How the resolved price is actually chosen at authorization time — contract override first, then policy, then tier — is specified with the fueling workflow in §3.4.

### 3.3. Fleet Accounts and Card Management

Fleet fueling runs on credit. A `NetworkOperator` creates a fleet account with an `account_name`, a `billing_email`, and a positive integer `credit_limit_cents` capping the outstanding balance; the account starts ACTIVE with `outstanding_balance_cents` at zero. That balance is always derivable as the sum of three components: the holds on the account's AUTHORIZED sessions, the `total_amount_cents` of its non-voided COMPLETED and SETTLED sessions, and any settlement penalties posted by month-close contract settlement.

Accounts may be suspended and later resumed by a `NetworkOperator`. Suspension requires the account to be ACTIVE, else `ERR_ACCOUNT_NOT_ACTIVE` (HTTP 409); resumption requires it to be SUSPENDED, else `ERR_ACCOUNT_NOT_SUSPENDED` (HTTP 409). Each transition increments the account's `version` by one. Closing an account is stronger: it requires ACTIVE status and an `outstanding_balance_cents` of exactly zero, else `ERR_OUTSTANDING_BALANCE_NONZERO` (HTTP 409), and on success the account becomes CLOSED — terminal — while every non-REVOKED card on the account cascades to REVOKED, each card's `version` incrementing by one.

Cards are issued against an account by a `FleetAccountManager` acting on their own account or by a `NetworkOperator`; a manager reaching for another account is stopped with `ERR_ACCOUNT_OWNERSHIP_MISMATCH`. Issuance requires the account to be ACTIVE (else `ERR_ACCOUNT_NOT_ACTIVE`), a `card_number` unique across all cards (a duplicate is `ERR_CARD_NUMBER_EXISTS`, HTTP 409), a `vehicle_plate` binding the card to a vehicle, and a positive `daily_gge_limit` capping per-card daily volume. A new card starts ACTIVE with `current_day_gge` at zero and `current_day_date` set to the current UTC date.

Card status is managed through a single transition capability accepting a target `to_status`. A card moves ACTIVE to SUSPENDED, SUSPENDED back to ACTIVE, and from either ACTIVE or SUSPENDED to the terminal REVOKED. Any attempt to change the status of an already REVOKED card is rejected with `ERR_CARD_ALREADY_REVOKED` (HTTP 409), and resuming a SUSPENDED card additionally requires its owning account to be ACTIVE, else `ERR_ACCOUNT_NOT_ACTIVE`. Every successful transition increments the card's `version` by one.

The card's `current_day_gge` is a running total of `settled_gge` across the card's non-voided COMPLETED and SETTLED sessions whose completion falls on `current_day_date`. It is maintained incrementally — incremented by `settled_gge` at completion, decremented by `settled_gge` (never below zero) when a COMPLETED session is voided — and the epoch sweep resets it to zero and re-dates it whenever the logical date has rolled past `current_day_date`. Card and account collections support filtering by `status`, cards additionally by `fleet_account_id`, and both are ownership-scoped for fleet-side readers per §2.10.

### 3.4. Fueling Sessions from Authorization to Settlement

Fueling begins with authorization, and there are two doors. A `FleetDriver` authorizes a private session by presenting the `fleet_card_id` they hold — their `X-User-ID` must equal it, else `ERR_CARD_OWNERSHIP_MISMATCH` — together with the `dispenser_id` they intend to fuel from, a `client_ref` idempotency reference, a positive `estimated_gge` used to size the hold, and `expected_fleet_account_version` per §2.9. An `Anonymous` customer authorizes a public session with just `dispenser_id`, `client_ref`, and `estimated_gge`; sending `fleet_card_id` to the public door is `ERR_INVALID_REQUEST`, and on a public session `fleet_card_id` and `fleet_account_id` remain null and the hold is zero. On either door the system stamps the new session AUTHORIZED with `authorized_at` set to the logical now, denormalizes `station_id` from the dispenser, and — for private sessions — denormalizes `fleet_account_id` from the card. The session's `access_type` records which door created it: PRIVATE or PUBLIC.

Authorization is gated in pipeline order. The card must be ACTIVE (`ERR_CARD_NOT_ACTIVE`, HTTP 409) and its account ACTIVE (`ERR_ACCOUNT_NOT_ACTIVE`); the dispenser must be IN_SERVICE (`ERR_DISPENSER_NOT_IN_SERVICE`, HTTP 409); the station must be ACTIVE (`ERR_STATION_NOT_ACTIVE`); the station's posture must not be OUTAGE (`ERR_STATION_OUTAGE`); and the station's `access_mode` must serve the requested access type — PUBLIC stations serve public sessions, PRIVATE stations private sessions, DUAL stations both — else `ERR_ACCESS_MODE_MISMATCH` (HTTP 409).

The unit price is resolved exactly once, at authorization, and frozen into `unit_price_cents`; completion reuses the snapshot rather than re-resolving. Resolution follows a pinned order. First, for a private session only: if an ACTIVE supply contract covers the session's account and station and the current calendar month falls between the contract's `start_month` and `end_month` inclusive, the price is the contract's `contract_price_per_gge_cents` and resolution stops — a contract overrides all policy pricing. Otherwise the system selects the ACTIVE pricing policy matching the station, an `access_scope` equal to the session's `access_type`, and a `fuel_type` equal to the dispensing unit's fuel, whose window contains the current instant (`effective_from` inclusive, `effective_to` exclusive). At most one such policy can exist, since creation supersedes same-key predecessors; if none matches, authorization fails with `ERR_NO_ACTIVE_PRICE` (HTTP 422). When a private session is priced from a policy carrying `tier_threshold_gge`, the account's month-to-date volume at that station — the sum of `settled_gge` over the account's non-voided COMPLETED and SETTLED private sessions there whose `completed_at` falls inside the current UTC calendar month, excluding the session being authorized — is compared against the threshold: at or above it, `tier_price_cents` applies; below it, `price_per_gge_cents`. Public sessions always pay `price_per_gge_cents`: no contract, no tier.

For private sessions the hold is then sized and two inclusive fiscal gates run. The hold, `hold_amount_cents`, is `estimated_gge` multiplied by the resolved unit price, rounded half-up to a whole cent. The account's `outstanding_balance_cents` plus the new hold must not exceed `credit_limit_cents` — equality is allowed, so an account may sit exactly at its limit — else the authorization is rejected with `ERR_CREDIT_LIMIT_EXCEEDED` (HTTP 402). The card's `current_day_gge` plus `estimated_gge` must not exceed `daily_gge_limit`, equality again allowed, else `ERR_DAILY_LIMIT_EXCEEDED` (HTTP 409). On success the hold posts: `outstanding_balance_cents` rises by `hold_amount_cents` and the account's `version` increments by one.

`client_ref` provides idempotency. It is unique per station among non-VOIDED sessions: retrying an authorization with the same `client_ref` and the same card returns the originally created session rather than duplicating it, while a `client_ref` already used at that station by a different card or access type is rejected with `ERR_DUPLICATE_CLIENT_REF` (HTTP 409). Once a session is VOIDED its reference may be reused.

Completion turns meter readings into money. The caller — for a private session the `FleetDriver` whose `X-User-ID` equals the session's card, else `ERR_CARD_OWNERSHIP_MISMATCH`; for a public session an `Anonymous` caller, any other role drawing `ERR_FORBIDDEN_ROLE` — supplies the positive `metered_mass_kg` actually dispensed. The session must still be AUTHORIZED, else `ERR_SESSION_NOT_COMPLETABLE` (HTTP 409). Completion computes two volumes from the constant 2.567 kilograms per GGE: `provisional_gge` is the metered mass divided by 2.567, rounded half-up to three decimals, ignoring calibration entirely; `settled_gge` multiplies the metered mass by `correction_factor_applied` — a snapshot of the dispenser's `correction_factor` taken at completion — before dividing by 2.567 and rounding half-up to three decimals. The two diverge whenever the dispenser's latest passing calibration reported a non-zero error; the provisional figure feeds meter-as-read reporting and provisional tax-credit claims, while the settled figure drives billing, daily card usage, contract delivered volume, and final tax-credit claims. `total_amount_cents` is `settled_gge` multiplied by the snapshot unit price, rounded half-up to a whole cent. For private sessions the account's balance rises by exactly the difference between `total_amount_cents` and the already-posted `hold_amount_cents`, the account `version` increments, and the card's `current_day_gge` rises by `settled_gge` with the card's `version` incrementing. The session lands in COMPLETED with `completed_at` stamped.

Voiding unwinds a session that has not yet settled. A session in AUTHORIZED or COMPLETED may be voided — anything else, including the terminal SETTLED and VOIDED states, draws `ERR_SESSION_NOT_VOIDABLE` (HTTP 409). The driver or the anonymous customer voids with an optional `reason`, recorded as `void_reason` CUSTOMER_REQUEST; a `StationManager` voids with MANAGER_VOID; system causes record TIMEOUT (the thirty-minute hold-timeout sweep of §2.5), STATION_OUTAGE (the cascade of §2.7), or INSPECTION_FAIL (§3.7). Voiding an AUTHORIZED private session releases its hold: the balance falls by `hold_amount_cents` and the account `version` increments. Voiding a COMPLETED private session refunds it: the balance falls by `total_amount_cents` — the hold having already been netted out at completion — the account `version` increments, and the card's `current_day_gge` falls by `settled_gge`, never below zero. Either way the session lands in VOIDED with `voided_at` stamped. Public sessions, carrying neither account nor card, simply change status.

Month close is handled by the clock: when the epoch sweep finds a COMPLETED session whose `completed_at` month is strictly earlier than the current month, the session becomes SETTLED and is stamped with `settled_at`. SETTLED is terminal and immutable — never voidable — and is exactly the population the final tax-credit computation draws on. Until the corresponding event occurs, `completed_at`, `voided_at`, `settled_at`, and `void_reason` are null on the session. Session collections support filtering by `station_id`, `fleet_account_id`, `fleet_card_id`, `dispenser_id`, `status`, and `month`.

### 3.5. Dispenser Calibration and Meter Accuracy

Meters drift, and the system tracks that drift explicitly. A `StationManager` records a calibration against a `dispenser_id` with the `measured_error_pct` observed on the test rig — a signed percentage to two decimal places, positive meaning over-delivery. The record's `result` is computed at creation: PASS when the absolute measured error is at most 0.50 percent — exactly 0.50 passes, while 0.51 fails — and FAIL otherwise. On a PASS the record's `applied_correction_factor` is one minus the measured error percentage divided by one hundred, carried to four decimal places (an over-delivery of 0.40 percent yields 0.9960); on a FAIL it is null. The record is stamped `performed_at` from the logical clock and is immutable thereafter, carrying only `id` and `created_at` among the common fields.

A passing calibration returns the dispenser to IN_SERVICE from whichever of IN_SERVICE, CALIBRATION_HOLD, or OUT_OF_SERVICE it occupied — including a recalibration of an already healthy dispenser, which is a self-transition that refreshes rather than moves it. In all PASS cases the dispenser's `correction_factor` adopts the record's applied value, `last_calibration_at` is set to now, `calibration_due_at` is pushed ninety days out, and the dispenser's `version` increments. A FAIL drives an IN_SERVICE or CALIBRATION_HOLD dispenser to OUT_OF_SERVICE with its `version` incrementing. Either outcome recomputes the station's uptime posture, and a FAIL that removes the last in-service dispenser can tip the station into OUTAGE and fire the §2.7 void cascade. Independently, the epoch sweep moves any IN_SERVICE dispenser whose `calibration_due_at` has passed to CALIBRATION_HOLD, which itself degrades the station's posture until a passing calibration clears it. Calibration records can be listed with optional `dispenser_id` and `result` filters.

### 3.6. Maintenance Windows and Backup Fueling Arrangements

Maintenance is planned as windows against either one compressor or the whole station. A `StationManager` schedules a window with `station_id`, an optional `compressor_id` — null marking a whole-station window — a `starts_at` that is inclusive, an `ends_at` that is exclusive and must be strictly later than `starts_at` (else `ERR_INVALID_TIME_RANGE`), and a `window_type` of PREVENTIVE, CORRECTIVE, or EMERGENCY. The window is born SCHEDULED. While any inspection at the station is OVERDUE, creating a non-EMERGENCY window is refused with `ERR_OVERDUE_INSPECTION`; EMERGENCY windows are exempt from that gate.

Scheduling enforces pairwise overlap discipline with a turnaround buffer. Windows are keyed by resource: a compressor-linked window conflicts only with other windows on that same compressor, a whole-station window only with other whole-station windows, and the two kinds never conflict with each other. Against each existing SCHEDULED or IN_PROGRESS window on the same resource, two half-open-interval tests run. If the new window starts before the existing window ends and the existing window starts before the new window ends, the two overlap and creation is rejected. Otherwise a turnaround buffer applies: when the new window starts at or after the existing window's end, the gap between that end and the new start must be at least two hours, and symmetrically when the existing window starts at or after the new window's end; a gap of exactly two hours is permitted. Any violation — overlap or insufficient buffer — is `ERR_WINDOW_OVERLAP` (HTTP 409). EMERGENCY windows skip the buffer but never the overlap test.

Starting a window requires it to be SCHEDULED, else `ERR_WINDOW_NOT_STARTABLE` (HTTP 409), and the logical now must fall within the window — on or after `starts_at` and strictly before `ends_at` — else `ERR_WINDOW_NOT_IN_TIME_RANGE` (HTTP 409). If the window names a compressor, that compressor must not already be UNDER_MAINTENANCE, else `ERR_COMPRESSOR_UNDER_MAINTENANCE`. There is also a continuity-of-service gate: starting a non-EMERGENCY window whose compressor is the station's only compressor in ONLINE or DEGRADED condition — or a whole-station window while any fueling capacity would be lost — requires an ACTIVATED backup arrangement whose `available_from` is on or before `starts_at` and whose `available_until` is on or after `ends_at`; without one the start is refused with `ERR_BACKUP_REQUIRED` (HTTP 409). On a successful start the window becomes IN_PROGRESS, its `version` increments, any linked compressor moves to UNDER_MAINTENANCE (its `version` incrementing as well), and the station posture is recomputed — if the station tips to OUTAGE, every AUTHORIZED session there is voided with STATION_OUTAGE and its hold released per §2.7.

Completing a window requires IN_PROGRESS, else `ERR_WINDOW_NOT_COMPLETABLE`; the window becomes COMPLETED and any linked compressor returns ONLINE, with posture recomputed. Cancelling requires SCHEDULED, else `ERR_WINDOW_NOT_CANCELLABLE`, and lands the window in CANCELLED. A window still SCHEDULED when its `ends_at` passes is swept to LAPSED. COMPLETED, CANCELLED, and LAPSED are terminal. Window collections filter by `station_id`, `compressor_id`, and `status`.

Backup fueling is the other half of continuity planning. A `StationManager` reserves capacity with the covered `station_id`, the `partner_station_code` providing backup fueling, an availability window whose `available_from` is inclusive and `available_until` exclusive and strictly later (else `ERR_INVALID_TIME_RANGE`), and a positive integer `committed_gge`. The arrangement starts RESERVED with `used_gge` at zero. Creation enforces aggregate-capacity semantics — deliberately different from the pairwise window rule: overlapping arrangements at the same station are allowed, but the sum of `committed_gge` over the station's existing RESERVED or ACTIVATED arrangements whose half-open availability intervals overlap the new one (two such intervals overlap when each starts before the other ends), plus the new arrangement's `committed_gge`, must not exceed the station's `backup_capacity_gge`; equality is permitted, and a breach is `ERR_BACKUP_CAPACITY_EXCEEDED` (HTTP 409).

Activation moves an arrangement from RESERVED to ACTIVATED and requires the logical now to lie within the availability window — on or after `available_from` and on or before `available_until`, both ends inclusive for this check alone; a RESERVED violation is `ERR_BACKUP_NOT_ACTIVATABLE` and an out-of-window attempt is `ERR_BACKUP_NOT_IN_WINDOW` (both HTTP 409). While ACTIVATED, partner draws are recorded against the arrangement: each draw supplies a `gge_amount`, requires ACTIVATED status (else `ERR_BACKUP_NOT_ACTIVE`, HTTP 409), and is accepted only while the running `used_gge` plus the new `gge_amount` stays at or below `committed_gge` — equality allowed — else `ERR_BACKUP_DRAW_EXCEEDED` (HTTP 409); accepted draws accumulate into `used_gge` and increment the arrangement's `version`. Releasing an arrangement requires ACTIVATED, else `ERR_BACKUP_NOT_RELEASABLE`, lands it in RELEASED, and freezes `used_gge`. The epoch sweep moves any RESERVED or ACTIVATED arrangement past its `available_until` to EXPIRED, likewise freezing `used_gge`; RELEASED and EXPIRED are terminal. Arrangement collections filter by `station_id` and `status`.

### 3.7. Safety Inspections and Compliance Enforcement

Inspections are scheduled by a `StationManager` with a `station_id`, an `inspection_type` of ANNUAL_COMPREHENSIVE, ODORIZATION_CHECK, or PRESSURE_VESSEL, and a `scheduled_for` instant; the inspection starts SCHEDULED. The epoch sweep marks any SCHEDULED inspection OVERDUE once the logical now passes `scheduled_for`, and an OVERDUE inspection is a hard block elsewhere: it stops station resumption (§3.1), claim submission (§3.9), and non-EMERGENCY window creation (§3.6), all with `ERR_OVERDUE_INSPECTION`.

Performance and approval are deliberately separated. A `StationManager` completes an inspection that is SCHEDULED or OVERDUE — any other state draws `ERR_INSPECTION_NOT_COMPLETABLE` (HTTP 409) — supplying a `result` of PASS, PASS_WITH_DEFICIENCIES, or FAIL plus optional `findings` text; the system stamps `performed_by` with the caller's `X-User-ID` and `completed_at` with the logical now. A `ComplianceOfficer` then approves a COMPLETED inspection, else `ERR_INSPECTION_NOT_APPROVABLE` (HTTP 409), and the approver's `X-User-ID` must differ from `performed_by` — an operator may never approve their own inspection — or the approval is refused with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). Approval stamps `approved_by` and moves the inspection to APPROVED, which is terminal.

Consequences hinge on the result. An approved FAIL suspends the station — its status becomes SUSPENDED with `version` incrementing — and voids every AUTHORIZED fueling session there with `void_reason` INSPECTION_FAIL, releasing each private session's hold (balance down by `hold_amount_cents`, account `version` up by one per session). An approved PASS or PASS_WITH_DEFICIENCIES instead auto-creates the station's next inspection of the same `inspection_type`, born SCHEDULED with `scheduled_for` set to the completed inspection's `completed_at` plus the interval for its type: 365 days for ANNUAL_COMPREHENSIVE, 90 days for ODORIZATION_CHECK, and 730 days for PRESSURE_VESSEL. Inspection collections filter by `station_id`, `status`, and `inspection_type`.

### 3.8. Supply Contracts and Monthly Shortfall Settlement

Fleet customers may hold throughput commitments. A `NetworkOperator` drafts a supply contract with `fleet_account_id`, `station_id`, a positive `committed_monthly_gge`, a positive `contract_price_per_gge_cents` that overrides policy pricing while in force (§3.4), non-negative `shortfall_tier1_rate_cents` and `shortfall_tier2_rate_cents` penalty rates, and a coverage span from `start_month` to `end_month`, both YYYY-MM strings with `end_month` not earlier than `start_month` (else `ERR_INVALID_TIME_RANGE`). The contract starts DRAFT.

Activation by a `NetworkOperator` moves a DRAFT contract to ACTIVE. It requires the contract still be DRAFT, else `ERR_CONTRACT_NOT_DRAFT` (HTTP 409); the account ACTIVE, else `ERR_ACCOUNT_NOT_ACTIVE`; the station ACTIVE, else `ERR_STATION_NOT_ACTIVE`; and no other ACTIVE contract already covering the same account-station pair, else `ERR_CONTRACT_ALREADY_ACTIVE` (HTTP 409). The epoch sweep expires an ACTIVE contract once the current calendar month is strictly later than its `end_month`, landing it in the terminal EXPIRED.

Settlement is run per contract and per month by a `NetworkOperator` naming the `month` to settle. The month must be strictly before the current logical month, else `ERR_MONTH_NOT_CLOSED` (HTTP 409); it must lie within the contract's span from `start_month` through `end_month` inclusive, else `ERR_MONTH_OUT_OF_CONTRACT` (HTTP 409); and no settlement may already exist for that contract and month, else `ERR_MONTH_ALREADY_SETTLED` (HTTP 409). Settlement then computes, for the settled month: `delivered_gge`, the sum of `settled_gge` over the contract account's non-voided private sessions at the contract station in COMPLETED or SETTLED status whose `completed_at` falls from midnight UTC on the first day of that month inclusive to midnight UTC on the first day of the following month exclusive; `shortfall_gge`, the committed volume minus the delivered volume, floored at zero; and a two-tier penalty. The tier cap is one-tenth of `committed_monthly_gge`; the portion of the shortfall up to that cap is charged at `shortfall_tier1_rate_cents` per GGE, and any remaining shortfall beyond the cap is charged at `shortfall_tier2_rate_cents` per GGE; the sum is rounded half-up to a whole cent and stored as `penalty_cents`. The result is persisted as an immutable MonthlySettlement carrying `supply_contract_id`, `month`, `delivered_gge`, `shortfall_gge`, `penalty_cents`, and a `settled_at` timestamp — and, being immutable, only `id` and `created_at` among the common fields. The penalty posts to the fleet account: `outstanding_balance_cents` rises by `penalty_cents` and the account's `version` increments by one. Settlements list with optional `supply_contract_id` and `month` filters, and contracts list with `fleet_account_id`, `station_id`, and `status` filters.

### 3.9. Fuel Tax Credit Claims

Alternative-fuel credits are claimed per station and period, under a strict segregation of duties: a `StationManager` drafts and finalizes, a `ComplianceOfficer` submits, and a `NetworkOperator` decides. Drafting a claim takes `station_id`, a `period_start` that is inclusive, and a `period_end` that is exclusive and must be strictly later, else `ERR_INVALID_TIME_RANGE`. The new period must not overlap the period of any SUBMITTED or APPROVED claim at the same station, else `ERR_CLAIM_PERIOD_OVERLAP` (HTTP 409). The claim starts DRAFT and its provisional figures are computed immediately.

Two computation variants exist, and both obey one pinned rounding discipline. Credit rates are fixed at fifty cents per GGE for CNG volume and one hundred cents per GGE for RNG volume, each session's fuel type coming from its dispenser. Rounding order is pinned: each session's GGE was already rounded to three decimal places at completion; the per-session rounded values are summed per fuel type with no re-rounding of the sums; and the claim amount is the CNG sum times fifty plus the RNG sum times one hundred, rounded half-up to a whole cent. Aggregating metered mass across sessions and converting once is forbidden — per-session rounded GGE values are the only admissible inputs.

The provisional variant, computed at creation and again at reopen, draws on the station's COMPLETED and SETTLED non-voided sessions whose `completed_at` falls inside the claim period, summing their `provisional_gge` into `eligible_gge_provisional` and pricing them into `claim_amount_provisional_cents`. Finalization — which requires the claim to be DRAFT, else `ERR_CLAIM_NOT_FINALIZABLE` (HTTP 409) — computes the final variant: only SETTLED sessions in the period, using their calibration-corrected `settled_gge`, and excluding any session already captured by another claim at the same station in FINALIZED, SUBMITTED, or APPROVED status, which prevents double-claiming. The results land in `eligible_gge_final` and `claim_amount_final_cents`, both null until this point, and the claim becomes FINALIZED. If that final eligible set is empty, finalization fails with `ERR_NO_ELIGIBLE_VOLUME` (HTTP 422).

Submission by a `ComplianceOfficer` requires the claim to be FINALIZED, else `ERR_CLAIM_NOT_SUBMITTABLE` (HTTP 409); the station must be ACTIVE, else `ERR_STATION_NOT_ACTIVE`; and no inspection at the station may be OVERDUE, else `ERR_OVERDUE_INSPECTION`. A submitted claim awaits decision by a `NetworkOperator`, who supplies an `outcome` and an optional `reason`; deciding requires SUBMITTED status, else `ERR_CLAIM_NOT_DECIDABLE` (HTTP 409). The claim lands APPROVED — terminal — or REJECTED, with the supplied text recorded as `decision_reason` in either case. A rejected claim is not dead: a `StationManager` may reopen it, which requires REJECTED status else `ERR_CLAIM_NOT_REOPENABLE` (HTTP 409), returning it to DRAFT, recomputing the provisional fields from current session data, and clearing both final fields back to null. Claim collections filter by `station_id` and `status`.

## 4. Endpoint Definitions

All endpoints return the standard envelope of §2.2. Creating a new resource returns HTTP 201 with the created resource; modifications, transitions, and reads return HTTP 200. Path variables shown in braces identify the target resource and are validated left to right per §2.8.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | `/_clock/set_current_utc` | Advance the logical clock and run all epoch sweeps | NetworkOperator |
| POST | `/cng/stations` | Create a station in SETUP with OUTAGE posture | NetworkOperator |
| GET | `/cng/stations` | List stations | NetworkOperator, StationManager, ComplianceOfficer, FleetAccountManager, FleetDriver |
| GET | `/cng/stations/{stationId}` | Get a station | NetworkOperator, StationManager, ComplianceOfficer, FleetAccountManager, FleetDriver |
| POST | `/cng/stations/{stationId}/activate` | Activate a SETUP station | NetworkOperator |
| POST | `/cng/stations/{stationId}/suspend` | Suspend an ACTIVE station, voiding its authorized sessions | NetworkOperator |
| POST | `/cng/stations/{stationId}/resume` | Resume a SUSPENDED station | NetworkOperator |
| POST | `/cng/compressors` | Register a compressor (ONLINE) | StationManager |
| GET | `/cng/compressors` | List compressors | NetworkOperator, StationManager, ComplianceOfficer, FleetAccountManager, FleetDriver |
| GET | `/cng/compressors/{compressorId}` | Get a compressor | NetworkOperator, StationManager, ComplianceOfficer, FleetAccountManager, FleetDriver |
| POST | `/cng/compressors/{compressorId}/report-condition` | Report compressor condition | StationManager |
| POST | `/cng/dispensers` | Register a dispenser (IN_SERVICE) | StationManager |
| GET | `/cng/dispensers` | List dispensers | NetworkOperator, StationManager, ComplianceOfficer, FleetAccountManager, FleetDriver |
| GET | `/cng/dispensers/{dispenserId}` | Get a dispenser | NetworkOperator, StationManager, ComplianceOfficer, FleetAccountManager, FleetDriver |
| POST | `/cng/calibration-records` | Record a dispenser calibration | StationManager |
| GET | `/cng/calibration-records` | List calibration records | NetworkOperator, StationManager, ComplianceOfficer, FleetAccountManager, FleetDriver |
| GET | `/cng/calibration-records/{recordId}` | Get a calibration record | NetworkOperator, StationManager, ComplianceOfficer, FleetAccountManager, FleetDriver |
| POST | `/cng/pricing-policies` | Create an ACTIVE pricing policy, superseding any same-key policy; OCC on the station | NetworkOperator |
| GET | `/cng/pricing-policies` | List pricing policies | NetworkOperator, StationManager, ComplianceOfficer, FleetAccountManager, FleetDriver |
| GET | `/cng/pricing-policies/{policyId}` | Get a pricing policy | NetworkOperator, StationManager, ComplianceOfficer, FleetAccountManager, FleetDriver |
| POST | `/cng/fleet-accounts` | Create a fleet account | NetworkOperator |
| GET | `/cng/fleet-accounts` | List fleet accounts (auto-scoped for fleet roles) | NetworkOperator, StationManager, ComplianceOfficer, FleetAccountManager, FleetDriver |
| GET | `/cng/fleet-accounts/{accountId}` | Get a fleet account (ownership-scoped) | NetworkOperator, StationManager, ComplianceOfficer, FleetAccountManager, FleetDriver |
| POST | `/cng/fleet-accounts/{accountId}/suspend` | Suspend an ACTIVE account | NetworkOperator |
| POST | `/cng/fleet-accounts/{accountId}/resume` | Resume a SUSPENDED account | NetworkOperator |
| POST | `/cng/fleet-accounts/{accountId}/close` | Close a zero-balance ACTIVE account, revoking its cards | NetworkOperator |
| POST | `/cng/fleet-cards` | Issue a fleet card | FleetAccountManager, NetworkOperator |
| GET | `/cng/fleet-cards` | List fleet cards (ownership-scoped) | NetworkOperator, StationManager, FleetAccountManager, FleetDriver |
| GET | `/cng/fleet-cards/{cardId}` | Get a fleet card (ownership-scoped) | NetworkOperator, StationManager, FleetAccountManager, FleetDriver |
| POST | `/cng/fleet-cards/{cardId}/set-status` | Change card status | FleetAccountManager, NetworkOperator |
| POST | `/cng/supply-contracts` | Create a supply contract in DRAFT | NetworkOperator |
| GET | `/cng/supply-contracts` | List supply contracts (ownership-scoped) | NetworkOperator, StationManager, ComplianceOfficer, FleetAccountManager |
| GET | `/cng/supply-contracts/{contractId}` | Get a supply contract | NetworkOperator, StationManager, ComplianceOfficer, FleetAccountManager |
| POST | `/cng/supply-contracts/{contractId}/activate` | Activate a DRAFT contract | NetworkOperator |
| POST | `/cng/supply-contracts/{contractId}/settle-month` | Settle a closed month, creating a MonthlySettlement | NetworkOperator |
| GET | `/cng/monthly-settlements` | List monthly settlements (ownership-scoped) | NetworkOperator, StationManager, ComplianceOfficer, FleetAccountManager |
| GET | `/cng/monthly-settlements/{settlementId}` | Get a monthly settlement | NetworkOperator, StationManager, ComplianceOfficer, FleetAccountManager |
| POST | `/cng/fueling-sessions/authorize` | Authorize a private fleet-card session; posts a hold; OCC on the account | FleetDriver |
| POST | `/cng/fueling-sessions/authorize-public` | Authorize a public cardless session with no hold | Anonymous |
| POST | `/cng/fueling-sessions/{sessionId}/complete` | Complete an AUTHORIZED session with the metered mass | FleetDriver, Anonymous |
| POST | `/cng/fueling-sessions/{sessionId}/void` | Void an AUTHORIZED or COMPLETED session | FleetDriver, Anonymous, StationManager |
| GET | `/cng/fueling-sessions` | List fueling sessions (ownership-scoped) | NetworkOperator, StationManager, ComplianceOfficer, FleetAccountManager, FleetDriver |
| GET | `/cng/fueling-sessions/{sessionId}` | Get a fueling session (ownership-scoped) | NetworkOperator, StationManager, ComplianceOfficer, FleetAccountManager, FleetDriver |
| POST | `/cng/maintenance-windows` | Schedule a maintenance window | StationManager |
| GET | `/cng/maintenance-windows` | List maintenance windows | NetworkOperator, StationManager, ComplianceOfficer, FleetAccountManager, FleetDriver |
| GET | `/cng/maintenance-windows/{windowId}` | Get a maintenance window | NetworkOperator, StationManager, ComplianceOfficer, FleetAccountManager, FleetDriver |
| POST | `/cng/maintenance-windows/{windowId}/start` | Start a SCHEDULED window inside its time range | StationManager |
| POST | `/cng/maintenance-windows/{windowId}/complete` | Complete an IN_PROGRESS window | StationManager |
| POST | `/cng/maintenance-windows/{windowId}/cancel` | Cancel a SCHEDULED window | StationManager |
| POST | `/cng/backup-arrangements` | Reserve backup fueling capacity | StationManager |
| GET | `/cng/backup-arrangements` | List backup arrangements | NetworkOperator, StationManager, ComplianceOfficer, FleetAccountManager, FleetDriver |
| GET | `/cng/backup-arrangements/{arrangementId}` | Get a backup arrangement | NetworkOperator, StationManager, ComplianceOfficer, FleetAccountManager, FleetDriver |
| POST | `/cng/backup-arrangements/{arrangementId}/activate` | Activate a RESERVED arrangement within its availability | StationManager |
| POST | `/cng/backup-arrangements/{arrangementId}/record-draw` | Record a partner-station backup draw | StationManager |
| POST | `/cng/backup-arrangements/{arrangementId}/release` | Release an ACTIVATED arrangement, freezing usage | StationManager |
| POST | `/cng/safety-inspections` | Schedule a safety inspection | StationManager |
| GET | `/cng/safety-inspections` | List safety inspections | NetworkOperator, StationManager, ComplianceOfficer, FleetAccountManager, FleetDriver |
| GET | `/cng/safety-inspections/{inspectionId}` | Get a safety inspection | NetworkOperator, StationManager, ComplianceOfficer, FleetAccountManager, FleetDriver |
| POST | `/cng/safety-inspections/{inspectionId}/complete` | Record an inspection result | StationManager |
| POST | `/cng/safety-inspections/{inspectionId}/approve` | Approve a COMPLETED inspection (never one's own) | ComplianceOfficer |
| POST | `/cng/tax-credit-claims` | Create a DRAFT claim with provisional amounts | StationManager |
| GET | `/cng/tax-credit-claims` | List tax credit claims | NetworkOperator, StationManager, ComplianceOfficer |
| GET | `/cng/tax-credit-claims/{claimId}` | Get a tax credit claim | NetworkOperator, StationManager, ComplianceOfficer |
| POST | `/cng/tax-credit-claims/{claimId}/finalize` | Finalize a DRAFT claim, computing the final variant | StationManager |
| POST | `/cng/tax-credit-claims/{claimId}/submit` | Submit a FINALIZED claim | ComplianceOfficer |
| POST | `/cng/tax-credit-claims/{claimId}/decision` | Approve or reject a SUBMITTED claim | NetworkOperator |
| POST | `/cng/tax-credit-claims/{claimId}/reopen` | Reopen a REJECTED claim to DRAFT | StationManager |

## 5. Error Code Catalogue

Trigger conditions for each error live in the §2 and §3 narratives; this catalogue fixes only the identifier-to-status mapping.

| Error ID | HTTP Status Code |
|---|---|
| ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER | 400 |
| ERR_FORBIDDEN_ROLE | 403 |
| ERR_ACCOUNT_OWNERSHIP_MISMATCH | 403 |
| ERR_CARD_OWNERSHIP_MISMATCH | 403 |
| ERR_INVALID_REQUEST | 400 |
| ERR_STATION_NOT_FOUND | 404 |
| ERR_COMPRESSOR_NOT_FOUND | 404 |
| ERR_DISPENSER_NOT_FOUND | 404 |
| ERR_CALIBRATION_RECORD_NOT_FOUND | 404 |
| ERR_PRICING_POLICY_NOT_FOUND | 404 |
| ERR_FLEET_ACCOUNT_NOT_FOUND | 404 |
| ERR_FLEET_CARD_NOT_FOUND | 404 |
| ERR_SUPPLY_CONTRACT_NOT_FOUND | 404 |
| ERR_MONTHLY_SETTLEMENT_NOT_FOUND | 404 |
| ERR_SESSION_NOT_FOUND | 404 |
| ERR_MAINTENANCE_WINDOW_NOT_FOUND | 404 |
| ERR_BACKUP_ARRANGEMENT_NOT_FOUND | 404 |
| ERR_INSPECTION_NOT_FOUND | 404 |
| ERR_TAX_CLAIM_NOT_FOUND | 404 |
| ERR_STATION_NOT_IN_SETUP | 409 |
| ERR_STATION_NOT_EQUIPPED | 409 |
| ERR_STATION_NOT_ACTIVE | 409 |
| ERR_STATION_NOT_SUSPENDED | 409 |
| ERR_COMPRESSOR_UNDER_MAINTENANCE | 409 |
| ERR_DISPENSER_NOT_IN_SERVICE | 409 |
| ERR_ACCOUNT_NOT_ACTIVE | 409 |
| ERR_ACCOUNT_NOT_SUSPENDED | 409 |
| ERR_CARD_NOT_ACTIVE | 409 |
| ERR_CARD_ALREADY_REVOKED | 409 |
| ERR_CONTRACT_NOT_DRAFT | 409 |
| ERR_CONTRACT_ALREADY_ACTIVE | 409 |
| ERR_SESSION_NOT_COMPLETABLE | 409 |
| ERR_SESSION_NOT_VOIDABLE | 409 |
| ERR_WINDOW_NOT_STARTABLE | 409 |
| ERR_WINDOW_NOT_IN_TIME_RANGE | 409 |
| ERR_WINDOW_NOT_COMPLETABLE | 409 |
| ERR_WINDOW_NOT_CANCELLABLE | 409 |
| ERR_BACKUP_NOT_ACTIVATABLE | 409 |
| ERR_BACKUP_NOT_IN_WINDOW | 409 |
| ERR_BACKUP_NOT_ACTIVE | 409 |
| ERR_BACKUP_NOT_RELEASABLE | 409 |
| ERR_INSPECTION_NOT_COMPLETABLE | 409 |
| ERR_INSPECTION_NOT_APPROVABLE | 409 |
| ERR_CLAIM_NOT_FINALIZABLE | 409 |
| ERR_CLAIM_NOT_SUBMITTABLE | 409 |
| ERR_CLAIM_NOT_DECIDABLE | 409 |
| ERR_CLAIM_NOT_REOPENABLE | 409 |
| ERR_STALE_STATION_VERSION | 412 |
| ERR_STALE_ACCOUNT_VERSION | 412 |
| ERR_STATION_OUTAGE | 409 |
| ERR_OVERDUE_INSPECTION | 409 |
| ERR_SEGREGATION_OF_DUTIES | 403 |
| ERR_BACKUP_REQUIRED | 409 |
| ERR_WINDOW_OVERLAP | 409 |
| ERR_BACKUP_CAPACITY_EXCEEDED | 409 |
| ERR_DUPLICATE_CLIENT_REF | 409 |
| ERR_CARD_NUMBER_EXISTS | 409 |
| ERR_MONTH_ALREADY_SETTLED | 409 |
| ERR_CLAIM_PERIOD_OVERLAP | 409 |
| ERR_ACCESS_MODE_MISMATCH | 409 |
| ERR_INVALID_TIME_RANGE | 422 |
| ERR_MONTH_NOT_CLOSED | 409 |
| ERR_MONTH_OUT_OF_CONTRACT | 409 |
| ERR_CREDIT_LIMIT_EXCEEDED | 402 |
| ERR_DAILY_LIMIT_EXCEEDED | 409 |
| ERR_NO_ACTIVE_PRICE | 422 |
| ERR_OUTSTANDING_BALANCE_NONZERO | 409 |
| ERR_NO_ELIGIBLE_VOLUME | 422 |
| ERR_BACKUP_DRAW_EXCEEDED | 409 |
