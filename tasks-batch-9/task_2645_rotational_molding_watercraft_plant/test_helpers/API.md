# `test_helpers` public API

This is the contract between `test_helpers/` and the test modules under
`test_suite/`. Everything listed here is importable directly from
`test_helpers`; nothing else in the package is public. Signatures are literal —
copy them, do not infer them.

```python
from test_helpers import (
    api_client, ApiErrorId, validate_success, validate_error, validate_paginated,
    ADMIN_HEADERS, PLANNER_HEADERS, AGENT_HEADERS, TEST_USERS,
    setup_scheduled_cycle, setup_sellable_units, setup_stored_units,
    setup_sealed_shipment, setup_delivered_units, setup_approved_claim,
)
```

`test_suite/conftest.py` is owned by the test-suite authors, not by this
package; the recommended content is given in the last section.

---

## 0. Conventions every test depends on

**Response envelope (PRD.md section 2.2).** Success bodies are
`{"meta": {...}, "response_type": "object" | "array", "data": ...}` and error
bodies are `{"meta": {...}, "response_type": "error", "data": {"error_id",
"message"}}`. There is no `success` boolean. Never index `res.json()["data"]`
by hand — use the framework validators (`validate_success`, `validate_error`,
`validate_paginated`) or the `api_client.read_*` accessors, which unwrap
centrally.

**HTTP statuses.** `api_errors` registers a complete `error_id -> status` map
with the framework on import, so `validate_error(res, ApiErrorId.X)` checks the
status for you. Pass an explicit status only when asserting something the map
cannot know.

**Headers.** Every `ApiClient` method takes `headers` as its last positional
parameter and defaults it to `None`, which sends no identity headers at all —
useful for the missing-identity cases. Use `ADMIN_HEADERS`, `PLANNER_HEADERS`,
`AGENT_HEADERS` for the three opaque roles. The four shop-floor roles and the
customer role are backed by rows in the database (PRD.md section 2.1), so their
headers must reference a real `Technician`/`Customer` id and cannot be
hardcoded: mint them with `create_technician(role_code)` /
`create_customer()`, or take the ones a fixture context already carries
(`resin_tech_headers`, `operator_headers`, `assembly_headers`,
`inspector_headers`, `customer_headers`).

**Clock.** The service never reads the host clock (PRD.md section 2.5). It
starts at `CLOCK_DEFAULT_UTC` (`"2026-08-01T00:00:00Z"`). Any test whose
outcome depends on ordering must call `set_clock(instant)` explicitly; every
fixture in this package already does so for the instants it needs. Setting the
clock forward is an active operation — it sweeps resin lots whose
`expires_on` has passed — so do not move the clock past a lot's expiry unless
that is the behaviour under test.

**Optimistic concurrency (PRD.md section 2.6).** Five writes carry an
`expected_<parent>_version` declaration. Always read the parent's current
`version` immediately before the write; the helpers
`production_order_version(id)`, `resin_lot_version(id)`,
`warehouse_version(id)`, `shipment_version(id)` and
`product_model_version(id)` do exactly that. `stale_version(v)` returns a value
guaranteed not to match, for the 412 cases.

**Numbers.** Money is integer cents — compare with `==` or
`assert_money_equals`. Every other decimal quantity is compared through
`assert_decimal_equals` / `assert_percent` / `dec()`; never compare floats and
never use `round()`, which rounds half to even. Rounding is ROUND_HALF_UP at
the scale PRD.md declares for the field (`SCALE_*` and `Q_*` constants).
Elapsed minutes are always floored (`elapsed_minutes_floor`).

**Data isolation.** The server is restarted before every individual test, so
each test starts against an empty database and must build all preconditions
itself. That is what the fixtures in section 9 are for; prefer them over
inlining a chain.

---

## 1. `api_client` — one method per endpoint

`api_client` is a ready-made module-level instance of `ApiClient`; the base URL
comes from `API_BASE_URL`. Every endpoint method returns the raw
`requests.Response` (so tests assert on status too). `payload` is sent as the
JSON body for POST/PATCH; `params` is sent as the query string for GET. Path
identifiers are always the first parameter. `headers` is always last and
defaults to `None` (no identity headers sent).

Abbreviations used in the tables: **H** = `headers: dict[str, str] \| None = None`,
**P** = `payload: dict[str, Any]`, **P?** = `payload: dict[str, Any] \| None = None`,
**Q?** = `params: dict[str, Any] \| None = None`. Endpoint methods all return
`requests.Response`.

| Method | Parameters | Endpoint | Purpose |
|---|---|---|---|
| `create_product_model` | `P, H` | `POST /product-models` | Create a product model (PRD.md 3.1). |
| `list_product_models` | `Q?, H` | `GET /product-models` | List product models with optional filters and pagination. |
| `get_product_model` | `product_model_id: str, H` | `GET /product-models/{product_model_id}` | Read one product model, including its current version. |
| `update_product_model` | `product_model_id: str, P, H` | `PATCH /product-models/{product_model_id}` | Patch mutable product model specification fields. |
| `create_mold` | `P, H` | `POST /molds` | Create a mould bound to a product model. |
| `list_molds` | `Q?, H` | `GET /molds` | List moulds with optional filters and pagination. |
| `get_mold` | `mold_id: str, H` | `GET /molds/{mold_id}` | Read one mould. |
| `service_hold_mold` | `mold_id: str, P?, H` | `POST /molds/{mold_id}/service-hold` | Put a mould on service hold; body may carry hold_note. |
| `complete_service_mold` | `mold_id: str, P?, H` | `POST /molds/{mold_id}/complete-service` | Return a mould from service hold; body may carry service_note. |
| `retire_mold` | `mold_id: str, P, H` | `POST /molds/{mold_id}/retire` | Retire a mould permanently. |
| `create_oven_station` | `P, H` | `POST /oven-stations` | Create an oven station with its arm count and changeover buffer. |
| `list_oven_stations` | `Q?, H` | `GET /oven-stations` | List oven stations with optional filters and pagination. |
| `get_oven_station` | `oven_station_id: str, H` | `GET /oven-stations/{oven_station_id}` | Read one oven station. |
| `mark_down_oven_station` | `oven_station_id: str, P, H` | `POST /oven-stations/{oven_station_id}/mark-down` | Take an oven station out of service. |
| `restore_oven_station` | `oven_station_id: str, H` | `POST /oven-stations/{oven_station_id}/restore` | Return an oven station to service. |
| `create_cooling_bay` | `P, H` | `POST /cooling-bays` | Create a cooling bay with its concurrent slot capacity. |
| `list_cooling_bays` | `Q?, H` | `GET /cooling-bays` | List cooling bays with optional filters and pagination. |
| `get_cooling_bay` | `cooling_bay_id: str, H` | `GET /cooling-bays/{cooling_bay_id}` | Read one cooling bay. |
| `mark_down_cooling_bay` | `cooling_bay_id: str, P, H` | `POST /cooling-bays/{cooling_bay_id}/mark-down` | Take a cooling bay out of service. |
| `restore_cooling_bay` | `cooling_bay_id: str, H` | `POST /cooling-bays/{cooling_bay_id}/restore` | Return a cooling bay to service. |
| `create_technician` | `P, H` | `POST /technicians` | Create a technician; role_code fixes which header role this row may act as. |
| `list_technicians` | `Q?, H` | `GET /technicians` | List technicians with optional filters and pagination. |
| `get_technician` | `technician_id: str, H` | `GET /technicians/{technician_id}` | Read one technician. |
| `suspend_technician` | `technician_id: str, P, H` | `POST /technicians/{technician_id}/suspend` | Suspend a technician. |
| `reinstate_technician` | `technician_id: str, H` | `POST /technicians/{technician_id}/reinstate` | Reinstate a suspended technician. |
| `create_customer` | `P, H` | `POST /customers` | Create a customer. |
| `list_customers` | `Q?, H` | `GET /customers` | List customers with optional filters and pagination. |
| `get_customer` | `customer_id: str, H` | `GET /customers/{customer_id}` | Read one customer. |
| `acknowledge_storage_guidance` | `customer_id: str, P, H` | `POST /customers/{customer_id}/acknowledge-storage-guidance` | Record a customer storage-guidance acknowledgement at a given instant. |
| `suspend_customer` | `customer_id: str, P, H` | `POST /customers/{customer_id}/suspend` | Suspend a customer. |
| `reinstate_customer` | `customer_id: str, H` | `POST /customers/{customer_id}/reinstate` | Reinstate a suspended customer. |
| `create_warehouse` | `P, H` | `POST /warehouses` | Create a warehouse with its zones and posture thresholds. |
| `list_warehouses` | `Q?, H` | `GET /warehouses` | List warehouses with optional posture filter and pagination. |
| `get_warehouse` | `warehouse_id: str, H` | `GET /warehouses/{warehouse_id}` | Read one warehouse, including its current version. |
| `get_warehouse_footprint_summary` | `warehouse_id: str, H` | `GET /warehouses/{warehouse_id}/footprint-summary` | Read the computed footprint projection for a warehouse. |
| `create_demand_forecast_bucket` | `P, H` | `POST /demand-forecast-buckets` | Create a demand forecast bucket for a model and season window. |
| `list_demand_forecast_buckets` | `Q?, H` | `GET /demand-forecast-buckets` | List demand forecast buckets with optional filters and pagination. |
| `get_demand_forecast_bucket` | `demand_forecast_bucket_id: str, H` | `GET /demand-forecast-buckets/{demand_forecast_bucket_id}` | Read one demand forecast bucket. |
| `create_resin_lot` | `P, H` | `POST /resin-lots` | Create a received resin lot. |
| `list_resin_lots` | `Q?, H` | `GET /resin-lots` | List resin lots with optional filters and pagination. |
| `get_resin_lot` | `resin_lot_id: str, H` | `GET /resin-lots/{resin_lot_id}` | Read one resin lot, including its ledger buckets and version. |
| `quarantine_resin_lot` | `resin_lot_id: str, P, H` | `POST /resin-lots/{resin_lot_id}/quarantine` | Quarantine a resin lot. |
| `release_resin_lot_quarantine` | `resin_lot_id: str, P, H` | `POST /resin-lots/{resin_lot_id}/release-quarantine` | Release a resin lot from quarantine. |
| `create_resin_charge` | `P, H` | `POST /resin-charges` | Reserve resin from a lot against a scheduled cycle. |
| `list_resin_charges` | `Q?, H` | `GET /resin-charges` | List resin charges with optional filters and pagination. |
| `get_resin_charge` | `resin_charge_id: str, H` | `GET /resin-charges/{resin_charge_id}` | Read one resin charge. |
| `release_resin_charge` | `resin_charge_id: str, P?, H` | `POST /resin-charges/{resin_charge_id}/release` | Release a reserved resin charge; body may carry release_reason. |
| `create_production_order` | `P, H` | `POST /production-orders` | Create a production order for a model and target warehouse. |
| `list_production_orders` | `Q?, H` | `GET /production-orders` | List production orders with optional filters and pagination. |
| `get_production_order` | `production_order_id: str, H` | `GET /production-orders/{production_order_id}` | Read one production order, including its current version. |
| `release_production_order` | `production_order_id: str, H` | `POST /production-orders/{production_order_id}/release` | Release a draft production order so cycles may be scheduled. |
| `cancel_production_order` | `production_order_id: str, P, H` | `POST /production-orders/{production_order_id}/cancel` | Cancel a production order. |
| `get_production_order_cost_summary` | `production_order_id: str, H` | `GET /production-orders/{production_order_id}/cost-summary` | Read the computed cost projection for a production order. |
| `create_molding_cycle` | `P, H` | `POST /molding-cycles` | Schedule a moulding cycle on an oven arm and cooling bay. |
| `list_molding_cycles` | `Q?, H` | `GET /molding-cycles` | List moulding cycles with optional filters and pagination. |
| `get_molding_cycle` | `molding_cycle_id: str, H` | `GET /molding-cycles/{molding_cycle_id}` | Read one moulding cycle. |
| `start_oven` | `molding_cycle_id: str, P, H` | `POST /molding-cycles/{molding_cycle_id}/start-oven` | Start the oven leg of a scheduled cycle. |
| `enter_cooling` | `molding_cycle_id: str, P, H` | `POST /molding-cycles/{molding_cycle_id}/enter-cooling` | End the oven leg and move the cycle into cooling. |
| `demold` | `molding_cycle_id: str, P, H` | `POST /molding-cycles/{molding_cycle_id}/demold` | End cooling, demould the cycle and mint its finished units. |
| `abort_molding_cycle` | `molding_cycle_id: str, P, H` | `POST /molding-cycles/{molding_cycle_id}/abort` | Abort a moulding cycle. |
| `list_finished_units` | `Q?, H` | `GET /finished-units` | List finished units with optional filters and pagination. |
| `get_finished_unit` | `finished_unit_id: str, H` | `GET /finished-units/{finished_unit_id}` | Read one finished unit. |
| `trim_finished_unit` | `finished_unit_id: str, P, H` | `POST /finished-units/{finished_unit_id}/trim` | Trim a demoulded hull. |
| `outfit_finished_unit` | `finished_unit_id: str, P, H` | `POST /finished-units/{finished_unit_id}/outfit` | Outfit a trimmed hull with its hardware kit. |
| `inspect_finished_unit` | `finished_unit_id: str, P, H` | `POST /finished-units/{finished_unit_id}/inspect` | Inspect an outfitted hull and record its verdict. |
| `scrap_finished_unit` | `finished_unit_id: str, P, H` | `POST /finished-units/{finished_unit_id}/scrap` | Scrap a finished unit. |
| `store_finished_unit` | `finished_unit_id: str, P, H` | `POST /finished-units/{finished_unit_id}/store` | Store a sellable unit into its target warehouse. |
| `release_storage` | `finished_unit_id: str, P, H` | `POST /finished-units/{finished_unit_id}/release-storage` | Release a stored unit back out of warehouse storage. |
| `create_shipment` | `P, H` | `POST /shipments` | Create a shipment trailer booking. |
| `list_shipments` | `Q?, H` | `GET /shipments` | List shipments with optional filters and pagination. |
| `get_shipment` | `shipment_id: str, H` | `GET /shipments/{shipment_id}` | Read one shipment, including its current version. |
| `seal_shipment` | `shipment_id: str, H` | `POST /shipments/{shipment_id}/seal` | Seal a shipment and quote its freight. |
| `unseal_shipment` | `shipment_id: str, P, H` | `POST /shipments/{shipment_id}/unseal` | Unseal a sealed shipment. |
| `depart_shipment` | `shipment_id: str, P, H` | `POST /shipments/{shipment_id}/depart` | Mark a sealed shipment departed. |
| `deliver_shipment` | `shipment_id: str, P, H` | `POST /shipments/{shipment_id}/deliver` | Mark a departed shipment delivered and bill its freight. |
| `cancel_shipment` | `shipment_id: str, P, H` | `POST /shipments/{shipment_id}/cancel` | Cancel a shipment. |
| `get_shipment_freight_summary` | `shipment_id: str, H` | `GET /shipments/{shipment_id}/freight-summary` | Read the computed freight projection for a shipment. |
| `create_shipment_line` | `P, H` | `POST /shipment-lines` | Add a stored unit to an open shipment. |
| `list_shipment_lines` | `Q?, H` | `GET /shipment-lines` | List shipment lines with optional filters and pagination. |
| `get_shipment_line` | `shipment_line_id: str, H` | `GET /shipment-lines/{shipment_line_id}` | Read one shipment line. |
| `remove_shipment_line` | `shipment_line_id: str, P, H` | `POST /shipment-lines/{shipment_line_id}/remove` | Remove a line from an open shipment. |
| `create_warranty_claim` | `P, H` | `POST /warranty-claims` | Submit a warranty claim against a delivered unit. |
| `list_warranty_claims` | `Q?, H` | `GET /warranty-claims` | List warranty claims with optional filters and pagination. |
| `get_warranty_claim` | `warranty_claim_id: str, H` | `GET /warranty-claims/{warranty_claim_id}` | Read one warranty claim. |
| `start_claim_review` | `warranty_claim_id: str, H` | `POST /warranty-claims/{warranty_claim_id}/start-review` | Move a submitted claim into review. |
| `submit_storage_review` | `warranty_claim_id: str, P, H` | `POST /warranty-claims/{warranty_claim_id}/storage-review` | Record the storage review outcome for a claim under review. |
| `waive_storage_finding` | `warranty_claim_id: str, P, H` | `POST /warranty-claims/{warranty_claim_id}/waive-storage-finding` | Waive a violated storage finding on a claim. |
| `approve_warranty_claim` | `warranty_claim_id: str, P, H` | `POST /warranty-claims/{warranty_claim_id}/approve` | Approve a claim and draw its payout from the model warranty reserve. |
| `deny_warranty_claim` | `warranty_claim_id: str, P, H` | `POST /warranty-claims/{warranty_claim_id}/deny` | Deny a claim under review. |
| `return_claim_to_queue` | `warranty_claim_id: str, P, H` | `POST /warranty-claims/{warranty_claim_id}/return-to-queue` | Return a claim under review to the submitted queue. |
| `void_warranty_claim` | `warranty_claim_id: str, P, H` | `POST /warranty-claims/{warranty_claim_id}/void` | Void an approved claim and restore its payout to the reserve. |
| `withdraw_warranty_claim` | `warranty_claim_id: str, P, H` | `POST /warranty-claims/{warranty_claim_id}/withdraw` | Withdraw a claim on the customer's behalf. |
| `set_clock` | `P, H` | `POST /_clock/set_current_utc` | Set the logical clock that drives every server-stamped instant. |
| `get_clock` | `H` | `GET /_clock/current_utc` | Read the logical clock's current instant. |

### Envelope unwrapping and typed projection accessors

These nine methods are the only place in the suite that reaches into `data`
directly. `read_entity` / `read_version` take the *name* of a getter method, e.g.
`api_client.read_version("get_production_order", order_id)`.

| Method | Parameters | Returns | Purpose |
|---|---|---|---|
| `read_data` | `response: requests.Response` | `dict[str, Any]` | Unwrap a success envelope and return its `data` object. |
| `read_entity` | `getter_name: str, entity_id: str, H` | `dict[str, Any]` | Call a `get_*` method by name and return the unwrapped entity. |
| `read_version` | `getter_name: str, entity_id: str, H` | `int` | Re-read an entity and return its current `version`. |
| `read_footprint_summary` | `warehouse_id: str, H` | `FootprintSummary` | Return the unwrapped warehouse footprint projection. |
| `read_cost_summary` | `production_order_id: str, H` | `CostSummary` | Return the unwrapped production order cost projection. |
| `read_freight_summary` | `shipment_id: str, H` | `FreightSummary` | Return the unwrapped shipment freight projection. |
| `read_clock` | `H` | `ClockState` | Return the unwrapped logical clock state (PRD.md section 2.5). |
| `read_current_utc` | `H` | `str` | Return only the logical clock's current instant as an ISO8601 string. |
| `set_current_utc` | `instant: str, H` | `dict[str, Any]` | Move the logical clock to `instant` and return the unwrapped result. |


---

## 2. `api_errors` — error identifiers and statuses

`ApiErrorId` is a `str`-valued `Enum`: the member name is the error id without
the `ERR_` prefix and the value is the full id as PRD.md section 5 spells it, so
`ApiErrorId.STALE_RESIN_LOT_VERSION == "ERR_STALE_RESIN_LOT_VERSION"` and the
member can be passed to `validate_error` directly or compared to a raw string.
`HTTP_STATUS_CODES: dict[str, int]` maps every full id to its status and is
registered with the framework on import, so `validate_error(res, ApiErrorId.X)`
already asserts the right status.

| `ApiErrorId` member | Value | HTTP |
|---|---|---|
| `MISSING_AUTH_HEADERS` | `ERR_MISSING_AUTH_HEADERS` | 401 |
| `INVALID_ROLE` | `ERR_INVALID_ROLE` | 401 |
| `IDENTITY_NOT_FOUND` | `ERR_IDENTITY_NOT_FOUND` | 401 |
| `ROLE_NOT_PERMITTED` | `ERR_ROLE_NOT_PERMITTED` | 403 |
| `ROLE_IDENTITY_MISMATCH` | `ERR_ROLE_IDENTITY_MISMATCH` | 403 |
| `CUSTOMER_SCOPE_VIOLATION` | `ERR_CUSTOMER_SCOPE_VIOLATION` | 403 |
| `SEGREGATION_OF_DUTIES` | `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `TECHNICIAN_SUSPENDED` | `ERR_TECHNICIAN_SUSPENDED` | 403 |
| `TECHNICIAN_NOT_CERTIFIED` | `ERR_TECHNICIAN_NOT_CERTIFIED` | 403 |
| `TECHNICIAN_ALREADY_ACTIVE` | `ERR_TECHNICIAN_ALREADY_ACTIVE` | 409 |
| `RESOURCE_NOT_FOUND` | `ERR_RESOURCE_NOT_FOUND` | 404 |
| `PRODUCT_MODEL_NOT_FOUND` | `ERR_PRODUCT_MODEL_NOT_FOUND` | 404 |
| `MOLD_NOT_FOUND` | `ERR_MOLD_NOT_FOUND` | 404 |
| `OVEN_STATION_NOT_FOUND` | `ERR_OVEN_STATION_NOT_FOUND` | 404 |
| `COOLING_BAY_NOT_FOUND` | `ERR_COOLING_BAY_NOT_FOUND` | 404 |
| `TECHNICIAN_NOT_FOUND` | `ERR_TECHNICIAN_NOT_FOUND` | 404 |
| `CUSTOMER_NOT_FOUND` | `ERR_CUSTOMER_NOT_FOUND` | 404 |
| `WAREHOUSE_NOT_FOUND` | `ERR_WAREHOUSE_NOT_FOUND` | 404 |
| `DEMAND_BUCKET_NOT_FOUND` | `ERR_DEMAND_BUCKET_NOT_FOUND` | 404 |
| `RESIN_LOT_NOT_FOUND` | `ERR_RESIN_LOT_NOT_FOUND` | 404 |
| `PRODUCTION_ORDER_NOT_FOUND` | `ERR_PRODUCTION_ORDER_NOT_FOUND` | 404 |
| `MOLDING_CYCLE_NOT_FOUND` | `ERR_MOLDING_CYCLE_NOT_FOUND` | 404 |
| `FINISHED_UNIT_NOT_FOUND` | `ERR_FINISHED_UNIT_NOT_FOUND` | 404 |
| `SHIPMENT_NOT_FOUND` | `ERR_SHIPMENT_NOT_FOUND` | 404 |
| `VALIDATION` | `ERR_VALIDATION` | 422 |
| `INVALID_ENUM_VALUE` | `ERR_INVALID_ENUM_VALUE` | 422 |
| `INVALID_QUANTITY` | `ERR_INVALID_QUANTITY` | 422 |
| `INVALID_WINDOW` | `ERR_INVALID_WINDOW` | 422 |
| `DUPLICATE_CODE` | `ERR_DUPLICATE_CODE` | 409 |
| `INSUFFICIENT_MEASUREMENTS` | `ERR_INSUFFICIENT_MEASUREMENTS` | 422 |
| `DEFORMATION_BELOW_THRESHOLD` | `ERR_DEFORMATION_BELOW_THRESHOLD` | 422 |
| `OVEN_STATION_DOWN` | `ERR_OVEN_STATION_DOWN` | 409 |
| `OVEN_STATION_ALREADY_OPERATIONAL` | `ERR_OVEN_STATION_ALREADY_OPERATIONAL` | 409 |
| `COOLING_BAY_DOWN` | `ERR_COOLING_BAY_DOWN` | 409 |
| `COOLING_BAY_ALREADY_OPERATIONAL` | `ERR_COOLING_BAY_ALREADY_OPERATIONAL` | 409 |
| `MOLD_NOT_AVAILABLE` | `ERR_MOLD_NOT_AVAILABLE` | 409 |
| `MOLD_HAS_ACTIVE_CYCLES` | `ERR_MOLD_HAS_ACTIVE_CYCLES` | 409 |
| `RESIN_LOT_NOT_AVAILABLE` | `ERR_RESIN_LOT_NOT_AVAILABLE` | 409 |
| `CHARGE_NOT_RELEASABLE` | `ERR_CHARGE_NOT_RELEASABLE` | 409 |
| `ORDER_NOT_SCHEDULABLE` | `ERR_ORDER_NOT_SCHEDULABLE` | 409 |
| `ORDER_ALREADY_TERMINAL` | `ERR_ORDER_ALREADY_TERMINAL` | 409 |
| `CYCLE_INVALID_STATE` | `ERR_CYCLE_INVALID_STATE` | 409 |
| `UNIT_INVALID_BUILD_STATE` | `ERR_UNIT_INVALID_BUILD_STATE` | 409 |
| `UNIT_INVALID_LOGISTICS_STATE` | `ERR_UNIT_INVALID_LOGISTICS_STATE` | 409 |
| `UNIT_NOT_REINSPECTABLE` | `ERR_UNIT_NOT_REINSPECTABLE` | 409 |
| `UNIT_NOT_DELIVERED` | `ERR_UNIT_NOT_DELIVERED` | 409 |
| `WAREHOUSE_FROZEN` | `ERR_WAREHOUSE_FROZEN` | 409 |
| `WAREHOUSE_POSTURE_RESTRICTED` | `ERR_WAREHOUSE_POSTURE_RESTRICTED` | 409 |
| `SHIPMENT_INVALID_STATE` | `ERR_SHIPMENT_INVALID_STATE` | 409 |
| `SHIPMENT_LINE_ALREADY_REMOVED` | `ERR_SHIPMENT_LINE_ALREADY_REMOVED` | 409 |
| `SHIPMENT_EMPTY` | `ERR_SHIPMENT_EMPTY` | 409 |
| `FREIGHT_QUOTE_MISSING` | `ERR_FREIGHT_QUOTE_MISSING` | 409 |
| `CLAIM_INVALID_STATE` | `ERR_CLAIM_INVALID_STATE` | 409 |
| `STORAGE_REVIEW_INCOMPLETE` | `ERR_STORAGE_REVIEW_INCOMPLETE` | 409 |
| `STORAGE_REVIEW_ALREADY_DONE` | `ERR_STORAGE_REVIEW_ALREADY_DONE` | 409 |
| `STORAGE_FINDING_NOT_WAIVABLE` | `ERR_STORAGE_FINDING_NOT_WAIVABLE` | 409 |
| `CUSTOMER_NOT_ACTIVE` | `ERR_CUSTOMER_NOT_ACTIVE` | 409 |
| `CUSTOMER_ALREADY_ACTIVE` | `ERR_CUSTOMER_ALREADY_ACTIVE` | 409 |
| `REGRIND_LIMIT_EXCEEDED` | `ERR_REGRIND_LIMIT_EXCEEDED` | 422 |
| `RESIN_LOT_NOT_QUALIFIED` | `ERR_RESIN_LOT_NOT_QUALIFIED` | 422 |
| `MELT_INDEX_OUT_OF_RANGE` | `ERR_MELT_INDEX_OUT_OF_RANGE` | 422 |
| `CHARGE_MASS_OUT_OF_TOLERANCE` | `ERR_CHARGE_MASS_OUT_OF_TOLERANCE` | 422 |
| `COOLING_TIME_INSUFFICIENT` | `ERR_COOLING_TIME_INSUFFICIENT` | 422 |
| `COOLING_MODE_MISMATCH` | `ERR_COOLING_MODE_MISMATCH` | 422 |
| `SIZE_CLASS_NOT_SUPPORTED` | `ERR_SIZE_CLASS_NOT_SUPPORTED` | 422 |
| `MOLD_SIZE_CLASS_MISMATCH` | `ERR_MOLD_SIZE_CLASS_MISMATCH` | 422 |
| `INVALID_MOLD_REPLACEMENT` | `ERR_INVALID_MOLD_REPLACEMENT` | 422 |
| `STORAGE_GUIDANCE_NOT_ACKNOWLEDGED` | `ERR_STORAGE_GUIDANCE_NOT_ACKNOWLEDGED` | 422 |
| `OVEN_WINDOW_CONFLICT` | `ERR_OVEN_WINDOW_CONFLICT` | 409 |
| `MOLD_WINDOW_CONFLICT` | `ERR_MOLD_WINDOW_CONFLICT` | 409 |
| `OVEN_START_IN_PAST` | `ERR_OVEN_START_IN_PAST` | 422 |
| `WAREHOUSE_MISMATCH` | `ERR_WAREHOUSE_MISMATCH` | 422 |
| `BUILD_AHEAD_WINDOW_MISMATCH` | `ERR_BUILD_AHEAD_WINDOW_MISMATCH` | 409 |
| `WARRANTY_TERM_EXPIRED` | `ERR_WARRANTY_TERM_EXPIRED` | 422 |
| `TRAILER_UNDERUTILIZED` | `ERR_TRAILER_UNDERUTILIZED` | 409 |
| `NO_ELIGIBLE_MOLD` | `ERR_NO_ELIGIBLE_MOLD` | 409 |
| `COOLING_BAY_CAPACITY_EXCEEDED` | `ERR_COOLING_BAY_CAPACITY_EXCEEDED` | 409 |
| `RESIN_INSUFFICIENT` | `ERR_RESIN_INSUFFICIENT` | 409 |
| `NO_ELIGIBLE_ZONE` | `ERR_NO_ELIGIBLE_ZONE` | 409 |
| `WAREHOUSE_CUBE_EXCEEDED` | `ERR_WAREHOUSE_CUBE_EXCEEDED` | 409 |
| `BUILD_AHEAD_CAP_EXCEEDED` | `ERR_BUILD_AHEAD_CAP_EXCEEDED` | 409 |
| `TRAILER_CUBE_EXCEEDED` | `ERR_TRAILER_CUBE_EXCEEDED` | 409 |
| `TRAILER_PAYLOAD_EXCEEDED` | `ERR_TRAILER_PAYLOAD_EXCEEDED` | 409 |
| `ORDER_OVERBUILD` | `ERR_ORDER_OVERBUILD` | 409 |
| `WARRANTY_RESERVE_EXHAUSTED` | `ERR_WARRANTY_RESERVE_EXHAUSTED` | 409 |
| `STALE_PRODUCTION_ORDER_VERSION` | `ERR_STALE_PRODUCTION_ORDER_VERSION` | 412 |
| `STALE_RESIN_LOT_VERSION` | `ERR_STALE_RESIN_LOT_VERSION` | 412 |
| `STALE_WAREHOUSE_VERSION` | `ERR_STALE_WAREHOUSE_VERSION` | 412 |
| `STALE_SHIPMENT_VERSION` | `ERR_STALE_SHIPMENT_VERSION` | 412 |
| `STALE_PRODUCT_MODEL_VERSION` | `ERR_STALE_PRODUCT_MODEL_VERSION` | 412 |


---

## 3. `types` — TypedDicts

All entity TypedDicts are `total=False` and inherit `CommonFields`, so a partial
response body still type-checks. They document field names; they do not validate
at runtime. Field names here are exactly the names PRD.md uses.

**`CommonFields`** — `id: str`, `created_at: str`, `updated_at: str`, `version: int`

**`ProductModel`** (extends `CommonFields`) — `model_code: str`, `hull_type: str`, `size_class: str`, `resin_grade: str`, `master_color_code: str`, `max_color_delta_e: float`, `required_additive_package_code: str`, `max_regrind_pct: float`, `min_melt_index_g10min: float`, `max_melt_index_g10min: float`, `nominal_charge_kg: float`, `charge_tolerance_pct: float`, `min_cooling_minutes: int`, `target_wall_thickness_mm: float`, `wall_thickness_min_mm: float`, `wall_cv_max_pct: float`, `impact_test_min_joules: float`, `gross_cube_m3: float`, `nest_factor: float`, `unit_weight_kg: float`, `msrp_cents: int`, `warranty_basis: str`, `initial_warranty_reserve_cents: int`, `warranty_reserve_cents: int`, `warranty_paid_cents: int`, `seasonal_family: str`

**`Mold`** (extends `CommonFields`) — `mold_code: str`, `product_model_id: str`, `size_class: str`, `cavity_count: int`, `nominal_charge_kg: float`, `service_interval_cycles: int`, `cycles_since_service: int`, `status: str`, `replaces_mold_id: str`

**`OvenStation`** (extends `CommonFields`) — `station_code: str`, `arm_count: int`, `max_size_class: str`, `changeover_buffer_min: int`, `energy_cents_per_min: int`, `status: str`

**`CoolingBay`** (extends `CommonFields`) — `bay_code: str`, `concurrent_slot_capacity: int`, `airflow_mode: str`, `status: str`

**`Technician`** (extends `CommonFields`) — `employee_code: str`, `full_name: str`, `role_code: str`, `certifications: list[Any]`, `status: str`

**`Customer`** (extends `CommonFields`) — `customer_code: str`, `email: str`, `region_code: str`, `storage_guidance_acknowledged_at: str`, `status: str`

**`Warehouse`** (extends `CommonFields`) — `site_code: str`, `footprint_capacity_cube_m3: float`, `zones: list[Any]`, `restricted_threshold_pct: float`, `frozen_threshold_pct: float`, `committed_cube_m3: float`, `utilization_pct: float`, `posture: str`

**`DemandForecastBucket`** (extends `CommonFields`) — `season_code: str`, `product_model_id: str`, `forecast_qty: int`, `build_ahead_cap_pct: float`, `build_ahead_cap_qty: int`, `build_ahead_committed_qty: int`, `window_start_on: str`, `window_end_on: str`

**`ResinLot`** (extends `CommonFields`) — `lot_code: str`, `resin_grade: str`, `melt_index_g10min: float`, `color_code: str`, `color_delta_e: float`, `additive_package_code: str`, `regrind_pct_by_mass: float`, `cost_cents_per_kg: int`, `received_kg: float`, `available_kg: float`, `reserved_kg: float`, `consumed_kg: float`, `expires_on: str`, `status: str`

**`ResinCharge`** (extends `CommonFields`) — `molding_cycle_id: str`, `resin_lot_id: str`, `created_by_technician_id: str`, `charge_kg: float`, `regrind_kg: float`, `virgin_kg: float`, `charge_regrind_pct: float`, `status: str`, `released_reason: str`

**`ProductionOrder`** (extends `CommonFields`) — `order_code: str`, `product_model_id: str`, `demand_bucket_id: str`, `target_warehouse_id: str`, `ordered_qty: int`, `completed_qty: int`, `scrapped_qty: int`, `status: str`, `blocked_reason: str`, `material_cost_cents: int`, `oven_energy_cost_cents: int`, `overhead_cents: int`, `total_cost_cents: int`, `unit_cost_cents: int`

**`MoldingCycle`** (extends `CommonFields`) — `production_order_id: str`, `mold_id: str`, `oven_station_id: str`, `arm_index: int`, `cooling_bay_id: str`, `operator_technician_id: str`, `oven_start_at: str`, `scheduled_oven_minutes: int`, `oven_end_at: str`, `scheduled_cooling_minutes: int`, `cooling_window_start_at: str`, `cooling_window_end_at: str`, `oven_temp_c: float`, `arm_rpm_major: float`, `arm_rpm_minor: float`, `cooling_mode: str`, `actual_oven_start_at: str`, `actual_oven_end_at: str`, `actual_cooling_end_at: str`, `actual_oven_minutes: int`, `actual_cooling_minutes: int`, `charged_mass_kg: float`, `weighted_melt_index_g10min: float`, `cycle_regrind_pct: float`, `provisional_warpage_index: float`, `status: str`, `abort_reason: str`

**`FinishedUnit`** (extends `CommonFields`) — `molding_cycle_id: str`, `product_model_id: str`, `warehouse_id: str`, `outfitted_by_technician_id: str`, `inspected_by_technician_id: str`, `hull_serial: str`, `cavity_index: int`, `trim_waste_kg: float`, `hardware_kit_serial: str`, `wall_thickness_points: list[Any]`, `mean_wall_thickness_mm: float`, `wall_sd_mm: float`, `wall_cv_pct: float`, `min_wall_thickness_mm: float`, `impact_test_joules: float`, `cosmetic_defect_grade: str`, `final_warpage_index: float`, `inspection_verdict: str`, `rework_count: int`, `build_status: str`, `logistics_status: str`, `storage_zone_code: str`, `stored_footprint_cube_m3: float`, `is_zone_anchor: bool`, `stored_at: str`, `demand_bucket_id: str`, `delivered_at: str`

**`Shipment`** (extends `CommonFields`) — `shipment_code: str`, `origin_warehouse_id: str`, `destination_zone: str`, `carrier_code: str`, `trailer_cube_capacity_m3: float`, `trailer_max_payload_kg: float`, `loaded_cube_m3: float`, `nested_cube_m3: float`, `loaded_weight_kg: float`, `cube_utilization_pct: float`, `density_kg_per_m3: float`, `quoted_freight_cents: int`, `billed_freight_cents: int`, `status: str`, `sealed_at: str`, `departed_at: str`, `delivered_at: str`

**`ShipmentLine`** (extends `CommonFields`) — `shipment_id: str`, `finished_unit_id: str`, `nest_position: int`, `line_gross_cube_m3: float`, `line_nested_cube_m3: float`, `line_freight_cents: int`, `status: str`

**`WarrantyClaim`** (extends `CommonFields`) — `claim_code: str`, `finished_unit_id: str`, `customer_id: str`, `claim_type: str`, `reported_deformation_mm: float`, `storage_description: str`, `claim_status: str`, `storage_review_status: str`, `months_in_service: int`, `payout_basis: str`, `pre_fee_gross_cents: int`, `storage_deduction_cents: int`, `admin_fee_cents: int`, `net_payout_cents: int`, `denial_reason: str`

**`FootprintZone`** — `zone_code: str`, `capacity_cube_m3: float`, `committed_cube_m3: float`, `remaining_cube_m3: float`, `anchor_product_model_ids: list[str]`, `stored_unit_count: int`

**`FootprintSummary`** — `warehouse_id: str`, `footprint_capacity_cube_m3: float`, `committed_cube_m3: float`, `remaining_cube_m3: float`, `utilization_pct: float`, `posture: str`, `zones: list[FootprintZone]`, `blocked_production_order_count: int`

**`CostSummary`** — `production_order_id: str`, `consumed_charge_count: int`, `material_cost_cents: int`, `demolded_cycle_count: int`, `oven_energy_cost_cents: int`, `pre_overhead_subtotal_cents: int`, `overhead_rate_pct: float`, `overhead_cents: int`, `total_cost_cents: int`, `completed_qty: int`, `unit_cost_cents: int | None`

**`FreightLine`** — `shipment_line_id: str`, `hull_serial: str`, `nest_position: int`, `line_gross_cube_m3: float`, `line_nested_cube_m3: float`, `chargeable_kg_nested: float`, `chargeable_kg_gross: float`, `line_freight_cents: int`

**`FreightSummary`** — `shipment_id: str`, `loaded_line_count: int`, `loaded_cube_m3: float`, `nested_cube_m3: float`, `loaded_weight_kg: float`, `cube_utilization_pct: float`, `density_kg_per_m3: float`, `discount_rate_pct: float`, `quoted_pre_discount_cents: int`, `quoted_freight_cents: int | None`, `billed_pre_discount_cents: int`, `billed_freight_cents: int | None`, `lines: list[FreightLine]`

**`ClockState`** — `current_utc: str`, `default_utc: str`

**`ClockAdvanceResult`** (extends `ClockState`) — `expired_resin_lot_count: int`, `released_resin_charge_count: int`, `aborted_molding_cycle_count: int`, `blocked_production_order_count: int`

**`PageMeta`** — `total_count: int`, `has_more: bool`, `limit: int`, `offset: int`

**`Headers`** — alias for `dict[str, str]`.


---

## 4. `constants` — enumerations, thresholds and scales

Every value below is taken from PRD.md. Enumeration tuples are the complete,
ordered member lists; use them for parametrised tests and for asserting that a
field's value is a legal member. `Q_*` values are `Decimal` quantisation
exponents for use with `dec()` / `assert_decimal_equals`.

| Constant | Value |
|---|---|
| `ROLE_PLANT_ADMIN` | `'PlantAdmin'` |
| `ROLE_RESIN_TECHNICIAN` | `'ResinTechnician'` |
| `ROLE_MOLDING_OPERATOR` | `'MoldingOperator'` |
| `ROLE_ASSEMBLY_TECHNICIAN` | `'AssemblyTechnician'` |
| `ROLE_QUALITY_INSPECTOR` | `'QualityInspector'` |
| `ROLE_LOGISTICS_PLANNER` | `'LogisticsPlanner'` |
| `ROLE_WARRANTY_AGENT` | `'WarrantyAgent'` |
| `ROLE_CUSTOMER` | `'Customer'` |
| `CERT_RESIN_BLENDING` | `'RESIN_BLENDING'` |
| `CERT_FIXTURE_ASSEMBLY` | `'FIXTURE_ASSEMBLY'` |
| `CERT_WALL_GAUGE` | `'WALL_GAUGE'` |
| `CERT_IMPACT_RIG` | `'IMPACT_RIG'` |
| `CLOCK_DEFAULT_UTC` | `'2026-08-01T00:00:00Z'` |
| `DEFAULT_PAGE_LIMIT` | `10` |
| `MIN_PAGE_LIMIT` | `1` |
| `MAX_PAGE_LIMIT` | `100` |
| `DEFAULT_PAGE_OFFSET` | `0` |
| `SCALE_MASS_KG` | `3` |
| `SCALE_CUBE_M3` | `4` |
| `SCALE_NEST_FACTOR` | `4` |
| `SCALE_PERCENT` | `2` |
| `SCALE_WALL_THICKNESS_MM` | `2` |
| `SCALE_WALL_STATS_MM` | `3` |
| `SCALE_OVEN_TEMP_C` | `1` |
| `SCALE_WARPAGE_INDEX` | `3` |
| `SCALE_DENSITY` | `3` |
| `Q_MASS` | `Decimal('0.001')` |
| `Q_CUBE` | `Decimal('0.0001')` |
| `Q_PERCENT` | `Decimal('0.01')` |
| `Q_WARPAGE` | `Decimal('0.001')` |
| `Q_TEMP` | `Decimal('0.1')` |
| `MIN_MEASUREMENT_POINTS` | `6` |
| `SD_DIVISOR` | `'population_n'` |
| `OVEN_TEMP_REFERENCE_C` | `Decimal('288')` |
| `OVEN_TEMP_SPAN_C` | `Decimal('40')` |
| `IDEAL_ROTATION_RATIO` | `Decimal('4.0')` |
| `W_THERMAL` | `Decimal('0.40')` |
| `W_COOLING` | `Decimal('0.35')` |
| `W_ROTATION` | `Decimal('0.25')` |
| `W_DISTRIBUTION` | `Decimal('0.50')` |
| `WARPAGE_INDEX_FLOOR` | `Decimal('0.000')` |
| `WARPAGE_INDEX_CEILING` | `Decimal('5.000')` |
| `WARPAGE_SCRAP_THRESHOLD` | `Decimal('2.500')` |
| `WARPAGE_REWORK_THRESHOLD` | `Decimal('1.200')` |
| `MAX_REWORK_COUNT` | `2` |
| `DEFORMATION_THRESHOLD_MM` | `Decimal('3.00')` |
| `OVERHEAD_TOP_RATE_PCT` | `Decimal('11.00')` |
| `DEFAULT_RESTRICTED_THRESHOLD_PCT` | `Decimal('85.00')` |
| `DEFAULT_FROZEN_THRESHOLD_PCT` | `Decimal('95.00')` |
| `THRESHOLD_COMPARISON` | `'greater_than_or_equal_triggers'` |
| `DEFAULT_BUILD_AHEAD_CAP_PCT` | `Decimal('60.00')` |
| `MAX_OVERBUILD_FACTOR` | `Decimal('1.20')` |
| `CAP_ROUNDING` | `'floor'` |
| `DIM_FACTOR_KG_PER_M3` | `Decimal('120.000')` |
| `FUEL_SURCHARGE_PCT` | `Decimal('9.50')` |
| `MIN_SEAL_UTILIZATION_PCT` | `Decimal('60.00')` |
| `WARRANTY_TERM_MONTHS` | `60` |
| `ADMIN_FEE_TOP_RATE_PCT` | `Decimal('5.00')` |
| `STORAGE_WAIVED_DEDUCTION_PCT` | `Decimal('35.00')` |
| `MONTHS_ROUNDING` | `'floor_complete_months'` |
| `MINUTE_ROUNDING` | `'floor'` |
| `OVEN_OCCUPANCY_MODE` | `'exclusive_per_arm'` |
| `OVEN_BOUNDARY` | `'half_open_with_symmetric_buffer'` |
| `COOLING_OCCUPANCY_MODE` | `'aggregate_slot_capacity'` |
| `COOLING_BOUNDARY` | `'closed_no_buffer'` |
| `SERVICE_COMPARISON` | `'greater_than_or_equal_triggers'` |
| `SERVICE_RESET` | `'to_zero'` |
| `MASS_INVARIANT` | `'available_kg + reserved_kg + consumed_kg == received_kg'` |
| `RESERVE_INVARIANT` | `'warranty_reserve_cents + warranty_paid_cents == initial_warranty_reserve_cents'` |
| `SERIAL_FORMAT` | `'<order_code>-<cavity_index:2>-<build_seq:4>'` |


---

## 5. `test_users` — role headers

PRD.md section 2.1 defines eight roles. Three are opaque identifiers that need no
database row, so ready-made header dicts exist for them. Four shop-floor roles are
backed by a `Technician` row whose `role_code` must match the claimed role, and the
customer role is backed by a `Customer` row, so headers for those five must name a
real row: build them from an id you just created (or take them from a fixture
context).

| Name | Kind | Notes |
|---|---|---|
| `ADMIN_HEADERS` | `dict[str, str]` | Ready-made PlantAdmin headers. |
| `PLANNER_HEADERS` | `dict[str, str]` | Ready-made LogisticsPlanner headers. |
| `AGENT_HEADERS` | `dict[str, str]` | Ready-made WarrantyAgent headers. |
| `NO_AUTH_HEADERS` | `dict[str, str]` | Empty dict — sends no identity at all. |
| `PLANT_ADMIN_USER_ID` | `str` | `admin-1` |
| `LOGISTICS_PLANNER_USER_ID` | `str` | `planner-1` |
| `WARRANTY_AGENT_USER_ID` | `str` | `agent-1` |
| `UNRESOLVABLE_TECHNICIAN_ID` | `str` | `00000000-0000-0000-0000-0000000000ff` |
| `UNRESOLVABLE_CUSTOMER_ID` | `str` | `00000000-0000-0000-0000-0000000000fe` |

| Builder | Parameters | Purpose |
|---|---|---|
| `make_plant_admin_headers` | `user_id: str=PLANT_ADMIN_USER_ID` | Headers for the PlantAdmin role; the identifier is opaque. |
| `make_logistics_planner_headers` | `user_id: str=LOGISTICS_PLANNER_USER_ID` | Headers for the LogisticsPlanner role; the identifier is opaque. |
| `make_warranty_agent_headers` | `user_id: str=WARRANTY_AGENT_USER_ID` | Headers for the WarrantyAgent role; the identifier is opaque. |
| `make_resin_technician_headers` | `user_id: str` | Headers for a ResinTechnician; `user_id` must be a RESIN_TECH row id. |
| `make_molding_operator_headers` | `user_id: str` | Headers for a MoldingOperator; `user_id` must be a MOLDING_OPERATOR row id. |
| `make_assembly_technician_headers` | `user_id: str` | Headers for an AssemblyTechnician; `user_id` must be an ASSEMBLY_TECH row id. |
| `make_quality_inspector_headers` | `user_id: str` | Headers for a QualityInspector; `user_id` must be a QUALITY_INSPECTOR row id. |
| `make_customer_headers` | `user_id: str` | Headers for a Customer; `user_id` must be a real Customer row id. |

`TECHNICIAN_HEADER_BUILDERS: dict[str, Callable[[str], dict[str, str]]]` is keyed by
`role_code` (`RESIN_TECH`, `MOLDING_OPERATOR`, `ASSEMBLY_TECH`, `QUALITY_INSPECTOR`).

`TEST_USERS` maps all eight role names to header dicts. Its three opaque entries
are usable as-is; the five entity-backed entries hold deliberately unresolvable
identifiers and exist only for the identity-resolution failure cases. Keys:

* `TEST_USERS["PlantAdmin"]`
* `TEST_USERS["LogisticsPlanner"]`
* `TEST_USERS["WarrantyAgent"]`
* `TEST_USERS["ResinTechnician"]`
* `TEST_USERS["MoldingOperator"]`
* `TEST_USERS["AssemblyTechnician"]`
* `TEST_USERS["QualityInspector"]`
* `TEST_USERS["Customer"]`


Every builder delegates to the framework's `build_user_headers(user_id, role)`, so a
header dict looks like
`{"X-User-ID": "...", "X-User-Role": "PlantAdmin", "Content-Type": "application/json"}`.
To claim a role with an identifier of your own choosing (for the mismatch cases)
call `build_user_headers(some_id, "QualityInspector")` directly.

---

## 6. `factories` — request-body builders

One builder per endpoint body. Every builder returns a plain `dict` and accepts
`**overrides`, which are applied last, so a caller can replace any default or add
a field the default omits (including sending a deliberately invalid value). Where a
field is optional in PRD.md the builder omits it unless asked. Codes that must be
unique across rows are suffixed automatically, so repeated calls never collide.

| Function | Parameters | Returns | Purpose |
|---|---|---|---|
| `unique_suffix` | `` | `str` | Return a short suffix that is unique within one test process. |
| `unique_code` | `prefix: str` | `str` | Return a globally unique code of the form `<prefix>-<suffix>`. |
| `product_model_payload` | `**overrides: Any` | `dict[str, Any]` | Body for POST /product-models. |
| `product_model_patch_payload` | `**overrides: Any` | `dict[str, Any]` | Body for PATCH /product-models/{product_model_id}. |
| `mold_payload` | `product_model_id: str, **overrides: Any` | `dict[str, Any]` | Body for POST /molds, matched to the default product model. |
| `oven_station_payload` | `**overrides: Any` | `dict[str, Any]` | Body for POST /oven-stations; two arms and a 15 minute changeover buffer. |
| `cooling_bay_payload` | `**overrides: Any` | `dict[str, Any]` | Body for POST /cooling-bays; two concurrent slots, forced air. |
| `technician_payload` | `role_code: str, **overrides: Any` | `dict[str, Any]` | Body for POST /technicians. |
| `customer_payload` | `**overrides: Any` | `dict[str, Any]` | Body for POST /customers. |
| `warehouse_payload` | `**overrides: Any` | `dict[str, Any]` | Body for POST /warehouses; one zone whose capacity is the site capacity. |
| `zone` | `zone_code: str, capacity_cube_m3: float` | `dict[str, Any]` | One element of a warehouse `zones` array. |
| `demand_forecast_bucket_payload` | `product_model_id: str, **overrides: Any` | `dict[str, Any]` | Body for POST /demand-forecast-buckets, with a window around the clock default. |
| `resin_lot_payload` | `**overrides: Any` | `dict[str, Any]` | Body for POST /resin-lots, qualified for the default product model. |
| `resin_charge_payload` | `molding_cycle_id: str, resin_lot_id: str, expected_resin_lot_version: int, **overrides: Any` | `dict[str, Any]` | Body for POST /resin-charges. |
| `production_order_payload` | `product_model_id: str, target_warehouse_id: str, **overrides: Any` | `dict[str, Any]` | Body for POST /production-orders; `demand_bucket_id` is left unset. |
| `molding_cycle_payload` | `production_order_id: str, oven_station_id: str, cooling_bay_id: str, expected_production_order_version: int, **overrides: Any` | `dict[str, Any]` | Body for POST /molding-cycles. |
| `start_oven_payload` | `actual_oven_start_at: str, **overrides: Any` | `dict[str, Any]` | Body for POST /molding-cycles/{molding_cycle_id}/start-oven. |
| `enter_cooling_payload` | `actual_oven_end_at: str, **overrides: Any` | `dict[str, Any]` | Body for POST /molding-cycles/{molding_cycle_id}/enter-cooling. |
| `demold_payload` | `actual_cooling_end_at: str, **overrides: Any` | `dict[str, Any]` | Body for POST /molding-cycles/{molding_cycle_id}/demold. |
| `abort_payload` | `abort_reason: str='OPERATOR_ABORT', **overrides: Any` | `dict[str, Any]` | Body for POST /molding-cycles/{molding_cycle_id}/abort. |
| `trim_payload` | `trim_waste_kg: float=0.4, **overrides: Any` | `dict[str, Any]` | Body for POST /finished-units/{finished_unit_id}/trim. |
| `outfit_payload` | `hardware_kit_serial: str \| None = None, **overrides: Any` | `dict[str, Any]` | Body for POST /finished-units/{finished_unit_id}/outfit. |
| `inspect_payload` | `**overrides: Any` | `dict[str, Any]` | Body for POST /finished-units/{finished_unit_id}/inspect that passes. |
| `store_payload` | `expected_warehouse_version: int, **overrides: Any` | `dict[str, Any]` | Body for POST /finished-units/{finished_unit_id}/store. |
| `release_storage_payload` | `release_reason: str='Zone rebalance', **overrides: Any` | `dict[str, Any]` | Body for POST /finished-units/{finished_unit_id}/release-storage. |
| `scrap_payload` | `scrap_reason: str='Delamination on the hull-deck seam', **overrides: Any` | `dict[str, Any]` | Body for POST /finished-units/{finished_unit_id}/scrap. |
| `shipment_payload` | `origin_warehouse_id: str, **overrides: Any` | `dict[str, Any]` | Body for POST /shipments. |
| `shipment_line_payload` | `shipment_id: str, finished_unit_id: str, expected_shipment_version: int, **overrides: Any` | `dict[str, Any]` | Body for POST /shipment-lines. |
| `remove_line_payload` | `remove_reason: str='Customer changed the delivery date', **overrides: Any` | `dict[str, Any]` | Body for POST /shipment-lines/{shipment_line_id}/remove. |
| `depart_payload` | `departed_at: str, **overrides: Any` | `dict[str, Any]` | Body for POST /shipments/{shipment_id}/depart. |
| `deliver_payload` | `delivered_at: str, **overrides: Any` | `dict[str, Any]` | Body for POST /shipments/{shipment_id}/deliver. |
| `unseal_payload` | `unseal_reason: str='Late line change requested by the dealer', **overrides: Any` | `dict[str, Any]` | Body for POST /shipments/{shipment_id}/unseal. |
| `cancel_shipment_payload` | `cancel_reason: str='Carrier cancelled the trailer', **overrides: Any` | `dict[str, Any]` | Body for POST /shipments/{shipment_id}/cancel. |
| `warranty_claim_payload` | `finished_unit_id: str, customer_id: str, **overrides: Any` | `dict[str, Any]` | Body for POST /warranty-claims. |
| `storage_review_payload` | `outcome: str='VERIFIED', storage_description: str=DEFAULT_STORAGE_DESCRIPTION, **overrides: Any` | `dict[str, Any]` | Body for POST /warranty-claims/{warranty_claim_id}/storage-review. |
| `waive_storage_finding_payload` | `waiver_note: str='Dealer handling error acknowledged; goodwill waiver granted.', **overrides: Any` | `dict[str, Any]` | Body for POST /warranty-claims/{warranty_claim_id}/waive-storage-finding. |
| `approve_claim_payload` | `expected_product_model_version: int, **overrides: Any` | `dict[str, Any]` | Body for POST /warranty-claims/{warranty_claim_id}/approve. |
| `deny_claim_payload` | `denial_reason: str='NOT_A_MANUFACTURING_DEFECT', **overrides: Any` | `dict[str, Any]` | Body for POST /warranty-claims/{warranty_claim_id}/deny. |
| `return_to_queue_payload` | `return_note: str='Hull photographs are illegible; re-open the file.', **overrides: Any` | `dict[str, Any]` | Body for POST /warranty-claims/{warranty_claim_id}/return-to-queue. |
| `void_claim_payload` | `void_reason: str='Adjuster re-opened the file after a second survey', **overrides: Any` | `dict[str, Any]` | Body for POST /warranty-claims/{warranty_claim_id}/void. |
| `withdraw_claim_payload` | `withdraw_reason: str='Owner changed their mind', **overrides: Any` | `dict[str, Any]` | Body for POST /warranty-claims/{warranty_claim_id}/withdraw. |
| `retire_mold_payload` | `retire_reason: str='Superseded by a new tool', **overrides: Any` | `dict[str, Any]` | Body for POST /molds/{mold_id}/retire. |
| `service_hold_payload` | `hold_note: str \| None = None, **overrides: Any` | `dict[str, Any]` | Body for POST /molds/{mold_id}/service-hold; the note is optional. |
| `complete_service_payload` | `service_note: str \| None = None, **overrides: Any` | `dict[str, Any]` | Body for POST /molds/{mold_id}/complete-service; the note is optional. |
| `mark_down_payload` | `down_reason: str='Burner service', **overrides: Any` | `dict[str, Any]` | Body for the oven station and cooling bay mark-down endpoints. |
| `suspend_payload` | `suspend_reason: str='Credit hold', **overrides: Any` | `dict[str, Any]` | Body for the technician and customer suspend endpoints. |
| `acknowledge_storage_guidance_payload` | `acknowledged_at: str=CLOCK_DEFAULT_UTC, **overrides: Any` | `dict[str, Any]` | Body for POST /customers/{customer_id}/acknowledge-storage-guidance. |
| `quarantine_payload` | `quarantine_reason: str='Colour drift audit', **overrides: Any` | `dict[str, Any]` | Body for POST /resin-lots/{resin_lot_id}/quarantine. |
| `release_quarantine_payload` | `release_note: str='Colour audit closed; lot returned to service', **overrides: Any` | `dict[str, Any]` | Body for POST /resin-lots/{resin_lot_id}/release-quarantine. |
| `release_charge_payload` | `release_reason: str \| None = None, **overrides: Any` | `dict[str, Any]` | Body for POST /resin-charges/{resin_charge_id}/release; the reason is optional. |
| `cancel_order_payload` | `cancel_reason: str='Customer withdrew the order', **overrides: Any` | `dict[str, Any]` | Body for POST /production-orders/{production_order_id}/cancel. |
| `clock_payload` | `current_utc: str=CLOCK_DEFAULT_UTC, **overrides: Any` | `dict[str, Any]` | Body for POST /_clock/set_current_utc. |


### Default bodies the builders produce

Literal output of each builder with no arguments beyond the required identifiers.
Unique codes carry a per-process suffix, shown here as it was generated. These
defaults are chosen to be accepted by PRD.md's validation rules and to produce a
PASS inspection verdict, so a test that wants a failure overrides exactly one field.

```python
# product_model_payload()
{
    "model_code": "PM-0017d57c9",
    "hull_type": "KAYAK",
    "size_class": "MID",
    "resin_grade": "HDPE_LINEAR",
    "master_color_code": "SEAFOAM",
    "max_color_delta_e": 1.5,
    "required_additive_package_code": "UV12",
    "max_regrind_pct": 30.0,
    "min_melt_index_g10min": 2.5,
    "max_melt_index_g10min": 6.0,
    "nominal_charge_kg": 12.0,
    "charge_tolerance_pct": 5.0,
    "min_cooling_minutes": 30,
    "target_wall_thickness_mm": 6.0,
    "wall_thickness_min_mm": 4.5,
    "wall_cv_max_pct": 12.0,
    "impact_test_min_joules": 90.0,
    "gross_cube_m3": 2.0,
    "nest_factor": 0.5,
    "unit_weight_kg": 24.0,
    "msrp_cents": 180000,
    "warranty_basis": "PRO_RATA_AGE",
    "initial_warranty_reserve_cents": 500000,
    "seasonal_family": "PADDLE"
}
# mold_payload(pm_id)
{
    "mold_code": "MLD-00259c801",
    "product_model_id": "<product_model_id>",
    "size_class": "MID",
    "cavity_count": 2,
    "nominal_charge_kg": 24.0,
    "service_interval_cycles": 10
}
# oven_station_payload()
{
    "station_code": "OV-0032b64b6",
    "arm_count": 2,
    "max_size_class": "OVERSIZE",
    "changeover_buffer_min": 15,
    "energy_cents_per_min": 100
}
# cooling_bay_payload()
{
    "bay_code": "CB-00446b2ad",
    "concurrent_slot_capacity": 2,
    "airflow_mode": "FORCED_AIR"
}
# technician_payload("RESIN_TECH")
{
    "employee_code": "T-0056c1ac4",
    "full_name": "Technician Resin_Tech",
    "role_code": "RESIN_TECH",
    "certifications": [
        "RESIN_BLENDING"
    ]
}
# customer_payload()
{
    "customer_code": "CUST-006614e1b",
    "email": "dealer.006614e1b@example.com",
    "region_code": "PNW"
}
# warehouse_payload()
{
    "site_code": "WH-0077bfd54",
    "footprint_capacity_cube_m3": 20.0,
    "zones": [
        {
            "zone_code": "Z-A",
            "capacity_cube_m3": 20.0
        }
    ],
    "restricted_threshold_pct": 85.0,
    "frozen_threshold_pct": 95.0
}
# demand_forecast_bucket_payload(pm_id)
{
    "season_code": "SSN-0087bbe19",
    "product_model_id": "<product_model_id>",
    "forecast_qty": 20,
    "build_ahead_cap_pct": 60.0,
    "window_start_on": "2026-07-01",
    "window_end_on": "2026-12-31"
}
# resin_lot_payload()
{
    "lot_code": "LOT-009a79f9e",
    "resin_grade": "HDPE_LINEAR",
    "melt_index_g10min": 4.0,
    "color_code": "SEAFOAM",
    "color_delta_e": 0.5,
    "additive_package_code": "UV12",
    "regrind_pct_by_mass": 10.0,
    "cost_cents_per_kg": 210,
    "received_kg": 500.0,
    "expires_on": "2027-12-31"
}
# production_order_payload(pm_id, wh_id)
{
    "order_code": "POR-010ff9ffc",
    "product_model_id": "<product_model_id>",
    "target_warehouse_id": "<target_warehouse_id>",
    "ordered_qty": 2
}
# molding_cycle_payload(order_id, station_id, bay_id, 2)
{
    "production_order_id": "<production_order_id>",
    "oven_station_id": "<oven_station_id>",
    "arm_index": 1,
    "cooling_bay_id": "<cooling_bay_id>",
    "oven_start_at": "2026-08-01T09:00:00Z",
    "scheduled_oven_minutes": 60,
    "scheduled_cooling_minutes": 30,
    "oven_temp_c": 288.0,
    "arm_rpm_major": 8.0,
    "arm_rpm_minor": 2.0,
    "cooling_mode": "FORCED_AIR",
    "expected_production_order_version": 2
}
# resin_charge_payload(cycle_id, lot_id, 1)
{
    "molding_cycle_id": "<molding_cycle_id>",
    "resin_lot_id": "<resin_lot_id>",
    "charge_kg": 24.0,
    "regrind_kg": 2.4,
    "expected_resin_lot_version": 1
}
# trim_payload()
{
    "trim_waste_kg": 0.4
}
# outfit_payload()
{
    "hardware_kit_serial": "HK-0119f087a"
}
# inspect_payload()
{
    "wall_thickness_points": [
        5.9,
        6.0,
        6.1,
        5.95,
        6.05,
        6.0
    ],
    "impact_test_joules": 120.0,
    "cosmetic_defect_grade": "A"
}
# store_payload(1)
{
    "expected_warehouse_version": 1
}
# shipment_payload(wh_id)
{
    "shipment_code": "SHP-012eda46b",
    "origin_warehouse_id": "<origin_warehouse_id>",
    "destination_zone": "Z2",
    "carrier_code": "CAR-A",
    "trailer_cube_capacity_m3": 5.0,
    "trailer_max_payload_kg": 200.0
}
# shipment_line_payload(shp_id, unit_id, 1)
{
    "shipment_id": "<shipment_id>",
    "finished_unit_id": "<finished_unit_id>",
    "expected_shipment_version": 1
}
# warranty_claim_payload(unit_id, cust_id)
{
    "claim_code": "WC-0131d0cf9",
    "finished_unit_id": "<finished_unit_id>",
    "customer_id": "<customer_id>",
    "claim_type": "HULL_DEFORMATION",
    "reported_deformation_mm": 4.5,
    "storage_description": "Kept on a padded cradle in a closed garage over the winter months."
}
# storage_review_payload()
{
    "outcome": "VERIFIED",
    "storage_description": "Kept on a padded cradle in a closed garage over the winter months."
}
# approve_claim_payload(3)
{
    "expected_product_model_version": 3
}
```



---

## 7. `assertions` — decimal, invariant and projection checks

These complement the framework validators; they never talk to the API themselves
except where noted. Decimal helpers all use ROUND_HALF_UP at the scale PRD.md
declares for the field in question.

| Function | Parameters | Returns | Purpose |
|---|---|---|---|
| `dec` | `value: Any` | `Decimal` | Convert a JSON number, numeric string or Decimal to an exact Decimal. |
| `round_half_up` | `value: Any, quantum: Decimal` | `Decimal` | Round `value` to `quantum` using the half-up rule of PRD.md section 2.4. |
| `floor_to` | `value: Any, quantum: Decimal=Decimal('1')` | `Decimal` | Truncate `value` toward zero, the rounding PRD.md uses for floors. |
| `assert_decimal_equals` | `actual: Any, expected: Any, quantum: Decimal, label: str='value'` | `None` | Assert two numbers agree once both are rounded half-up to `quantum`. |
| `assert_money_equals` | `actual: Any, expected: int, label: str='amount'` | `None` | Assert a money field equals `expected`. |
| `decimal_places` | `value: Any` | `int` | Return how many digits `value` carries after the decimal point. |
| `assert_at_most_scale` | `value: Any, places: int, label: str='value'` | `None` | Assert `value` carries no more decimal places than PRD.md declares. |
| `assert_percent` | `value: Any, label: str='percentage'` | `None` | Assert a percentage sits in 0.00 to 100.00 at two decimals. |
| `parse_utc` | `instant: str` | `datetime` | Parse an ISO 8601 UTC instant with a trailing Z. |
| `format_utc` | `moment: datetime` | `str` | Render a datetime as an ISO 8601 UTC instant with a trailing Z. |
| `shift_minutes` | `instant: str, minutes: int` | `str` | Return `instant` advanced by `minutes` whole minutes. |
| `shift_days` | `instant: str, days: int` | `str` | Return `instant` advanced by `days` whole days. |
| `elapsed_minutes_floor` | `start: str, end: str` | `int` | Whole minutes between two instants, floored as PRD.md section 2.9 requires. |
| `assert_instant_equals` | `actual: Any, expected: str, label: str='instant'` | `None` | Assert two ISO 8601 UTC instants denote the same moment. |
| `assert_common_fields` | `entity: dict[str, Any], label: str='entity'` | `None` | Assert the four fields PRD.md section 2.4 puts on every row are present. |
| `assert_version_unchanged` | `before: dict[str, Any], after: dict[str, Any], label: str='entity'` | `None` | Assert a refused write left the row's version untouched. |
| `assert_unchanged` | `before: dict[str, Any], after: dict[str, Any], fields: list[str], label: str='entity'` | `None` | Assert none of `fields` moved between two reads of the same row. |
| `assert_null_fields` | `entity: dict[str, Any], fields: list[str], label: str='entity'` | `None` | Assert every named field is null, as PRD.md requires before it is set. |
| `assert_pagination_meta` | `meta: dict[str, Any], expected_total: int, limit: int, offset: int` | `None` | Assert the four pagination fields PRD.md section 2.3 declares. |
| `assert_resin_ledger_conserved` | `lot: dict[str, Any]` | `None` | Assert available_kg + reserved_kg + consumed_kg equals received_kg. |
| `assert_warranty_reserve_conserved` | `model: dict[str, Any]` | `None` | Assert warranty_reserve_cents + warranty_paid_cents equals the initial reserve. |
| `assert_cycle_window_projection` | `cycle: dict[str, Any]` | `None` | Assert the three projected window stamps follow from the scheduled minutes. |
| `assert_elapsed_minutes_floored` | `cycle: dict[str, Any], field: str, start_field: str, end_field: str` | `None` | Assert an elapsed-minute field is the floored difference of two stamps. |
| `assert_warpage_index_shape` | `value: Any, label: str='warpage index'` | `None` | Assert a warpage index is three decimals clamped to 0.000 through 5.000. |
| `expected_wall_statistics` | `points: list[float]` | `dict[str, Decimal]` | Return the wall statistics PRD.md derives from a set of readings. |
| `assert_wall_statistics` | `unit: dict[str, Any], points: list[float]` | `None` | Assert a hull's wall statistics match the readings it was inspected with. |
| `assert_hull_serial_format` | `hull_serial: str, order_code: str, cavity_index: int` | `None` | Assert a hull serial follows the deterministic format PRD.md declares. |
| `assert_footprint_summary_consistent` | `summary: dict[str, Any]` | `None` | Assert the footprint projection agrees with itself. |
| `assert_posture_for_utilization` | `posture: str, utilization_pct: Any, restricted_threshold_pct: Any, frozen_threshold_pct: Any` | `None` | Assert the posture PRD.md selects for a utilisation. |
| `assert_freight_summary_consistent` | `summary: dict[str, Any]` | `None` | Assert the freight projection agrees with itself. |
| `assert_claim_payout_arithmetic` | `claim: dict[str, Any]` | `None` | Assert a claim's four money fields agree with one another. |

---

## 8. `fixtures` — composite setups

Every helper here is a **plain function**, not a pytest fixture: call it inside the
test body. Each returns a `dict` called a *context*. A context returned by a lower
rung can be passed to a higher rung via the `baseline=` keyword, and each rung
threads the keyword arguments it does not consume down to the rung below it, so
`setup_approved_claim(model_overrides={"msrp_cents": 250000})` reaches all the way
down to the product model.

Three guarantees hold for every helper: the shop-floor identities it created are in
the context (never hardcoded), any version it hands out was read immediately before
use, and the logical clock is set explicitly rather than assumed.

### The ladder

```
create_plant_baseline            model, mould, oven station, cooling bay,
  |                              4 technicians, warehouse
setup_scheduled_cycle            + resin lot, released order, SCHEDULED cycle,
  |                              RESERVED charge
run_cycle_to_oven_running        + actual_oven_start_at set, cycle OVEN_RUNNING
run_cycle_to_cooling             + actual_oven_end_at set, cycle COOLING
run_cycle_to_demold  ==  setup_demolded_units
  |                              cycle DEMOLDED, charge CONSUMED, one
  |                              FinishedUnit per cavity in GREEN
setup_sellable_units             each hull TRIMMED -> OUTFITTED -> inspected PASS,
  |                              build_status SELLABLE, logistics UNALLOCATED
setup_stored_units               + hulls STORED in a zone, warehouse cube committed
setup_loaded_shipment            + PLANNED->LOADING shipment with one line per hull,
  |                              hulls LOADED
setup_sealed_shipment            shipment SEALED, quoted_freight_cents set
setup_departed_shipment          shipment IN_TRANSIT, departed_at set
setup_delivered_units            shipment DELIVERED, hulls DELIVERED, billed freight
setup_delivered_unit_with_customer  + an ACTIVE Customer that acknowledged guidance
setup_submitted_claim            + SUBMITTED WarrantyClaim
setup_claim_under_review         claim UNDER_REVIEW
setup_claim_storage_verified / _violated / _waived   storage axis resolved
setup_approved_claim             claim APPROVED, reserve drawn down
```

### Reference

#### `set_clock(instant: str, headers: dict[str, str] | None = None) -> dict[str, Any]`

Move the logical clock and return the sweep counters the call reports.

Only PlantAdmin may move the clock, so the admin headers are the default.

#### `reset_clock() -> dict[str, Any]`

Put the logical clock back on its startup default of 2026-08-01T00:00:00Z.

#### `current_utc(headers: dict[str, str] | None = None) -> str`

Read the logical clock's current instant.

#### `stale_version(version: int) -> int`

Return a version number that cannot match `version`.

Useful for the five concurrency guards of PRD.md section 2.6, each of which
refuses a write whose declared version differs from the stored one.

#### `warehouse_version(warehouse_id: str) -> int`

Re-read a warehouse and return its current version.

#### `production_order_version(production_order_id: str) -> int`

Re-read a production order and return its current version.

#### `resin_lot_version(resin_lot_id: str) -> int`

Re-read a resin lot and return its current version.

#### `shipment_version(shipment_id: str) -> int`

Re-read a shipment and return its current version.

#### `product_model_version(product_model_id: str) -> int`

Re-read a product model and return its current version.

#### `create_technician(role_code: str, **overrides: Any) -> dict[str, Any]`

Create one Technician and mint the headers that let it act.

Returns `{"technician", "technician_id", "headers"}`. The technician is
ACTIVE and holds exactly the certifications PRD.md requires for
`role_code`, so it can act immediately.

#### `create_customer(*, acknowledged_at: str | None = None, **overrides: Any) -> dict[str, Any]`

Create one ACTIVE Customer and mint its headers.

Returns `{"customer", "customer_id", "headers"}`. When
`acknowledged_at` is given, the storage guidance acknowledgement is
recorded at that instant, which is what a later VERIFIED storage review
requires: PRD.md section 3.9 needs the acknowledgement to fall at or before
the hull's `delivered_at`.

#### `create_plant_baseline(*, clock: str | None=CLOCK_DEFAULT_UTC, model_overrides: dict[str, Any] | None = None, mold_overrides: dict[str, Any] | None = None, station_overrides: dict[str, Any] | None = None, bay_overrides: dict[str, Any] | None = None, warehouse_overrides: dict[str, Any] | None = None) -> dict[str, Any]`

Stand up the reference data every production workflow needs.

Creates, in the order PRD.md section 3.1 describes: one ProductModel, one
Mold bound to it, one OvenStation, one CoolingBay, one Technician for each
of the four shop-floor roles, and one Warehouse. When `clock` is not None
the logical clock is set to it first, so the whole context is built at a
known instant.

Every created row is in its initial state: the mould AVAILABLE with
`cycles_since_service` 0, both equipment rows OPERATIONAL, all four
technicians ACTIVE, and the warehouse NORMAL with zero committed cube.

Returns a context carrying each entity, its id, and the four sets of
shop-floor headers under the keys `resin_tech_headers`,
`operator_headers`, `assembly_headers` and `inspector_headers`.

#### `create_resin_lot(**overrides: Any) -> dict[str, Any]`

Create one AVAILABLE resin lot qualified for the default product model.

On intake `available_kg` equals `received_kg` and the other two ledger
buckets are zero, as PRD.md section 2.8 requires.

#### `create_demand_bucket(ctx: dict[str, Any], **overrides: Any) -> dict[str, Any]`

Create a demand forecast bucket for the context's product model.

The default window spans 2026-07-01 through 2026-12-31, so the clock's
startup date falls inside it and a store is admitted on the window test.

#### `create_production_order(ctx: dict[str, Any], *, release: bool=True, **overrides: Any) -> dict[str, Any]`

Create a production order against the context's model and warehouse.

With `release` true the order is also released, which PRD.md section 3.3
moves from DRAFT to READY_TO_SCHEDULE and is the precondition for
scheduling a cycle. With `release` false the order is left in DRAFT.

#### `schedule_cycle(ctx: dict[str, Any], production_order: dict[str, Any], **overrides: Any) -> dict[str, Any]`

Schedule one cycle on the context's station arm 1 and cooling bay.

The order's version is re-read immediately before the write, so
`expected_production_order_version` is never stale. The mould is chosen by
the server. The new cycle is SCHEDULED and its window projections follow
from `oven_start_at` and the two scheduled durations.

#### `reserve_charge(ctx: dict[str, Any], molding_cycle: dict[str, Any], resin_lot: dict[str, Any], **overrides: Any) -> dict[str, Any]`

Reserve resin from `resin_lot` against `molding_cycle`.

The lot's version is re-read immediately before the write. The resulting
charge is RESERVED and the lot's ledger has moved the charge mass from
`available_kg` to `reserved_kg`.

#### `setup_scheduled_cycle(*, baseline: dict[str, Any] | None = None, order_overrides: dict[str, Any] | None = None, cycle_overrides: dict[str, Any] | None = None, lot_overrides: dict[str, Any] | None = None, charge_overrides: dict[str, Any] | None = None, charge: bool=True, **baseline_kwargs: Any) -> dict[str, Any]`

Build a plant, a qualified lot, a released order and one SCHEDULED cycle.

Creates, on top of `create_plant_baseline`: one AVAILABLE ResinLot, one
ProductionOrder released to READY_TO_SCHEDULE, one SCHEDULED MoldingCycle
on arm 1, and — unless `charge` is false — one RESERVED ResinCharge
covering the mould's full shot mass.

Adds the keys `resin_lot`, `resin_lot_id`, `production_order`,
`production_order_id`, `molding_cycle`, `molding_cycle_id` and
`resin_charge`/`resin_charge_id` to the context it returns.

#### `run_cycle_to_oven_running(ctx: dict[str, Any], *, actual_oven_start_at: str=DEFAULT_OVEN_START) -> dict[str, Any]`

Start the oven leg, leaving the cycle OVEN_RUNNING.

The clock is set to the same instant that is stamped as
`actual_oven_start_at`, so the run is anchored on a known clock reading.

#### `run_cycle_to_cooling(ctx: dict[str, Any], *, actual_oven_start_at: str=DEFAULT_OVEN_START, actual_oven_end_at: str=DEFAULT_OVEN_END) -> dict[str, Any]`

Take a SCHEDULED cycle through the oven leg into COOLING.

Sets the clock to each instant before stamping it. On return the cycle is
COOLING with `actual_oven_minutes` floored from the two oven stamps.

#### `run_cycle_to_demold(ctx: dict[str, Any], *, actual_oven_start_at: str=DEFAULT_OVEN_START, actual_oven_end_at: str=DEFAULT_OVEN_END, actual_cooling_end_at: str=DEFAULT_COOLING_END) -> dict[str, Any]`

Take a cycle all the way to DEMOLDED and collect the hulls it minted.

The default instants give a sixty minute oven leg and a thirty-five minute
cooling leg, which clears the default model's `min_cooling_minutes` of 30.
Demoulding consumes the reserved charge, scores
`provisional_warpage_index`, advances the mould's service counter and
mints one FinishedUnit per cavity — two with the default mould.

Adds `finished_units` (ordered by `cavity_index`) and
`finished_unit_ids` to the context.

#### `list_units_for_cycle(molding_cycle_id: str) -> list[dict[str, Any]]`

Return the hulls a cycle minted, ordered by `cavity_index`.

#### `setup_demolded_units(**kwargs: Any) -> dict[str, Any]`

Shortcut to a DEMOLDED cycle whose hulls exist and are UNALLOCATED.

Every hull is `build_status` DEMOLDED, `logistics_status` UNALLOCATED
and `inspection_verdict` PENDING.

#### `advance_unit_to_outfitted(ctx: dict[str, Any], unit: dict[str, Any], *, trim_waste_kg: float=0.4, hardware_kit_serial: str | None = None) -> dict[str, Any]`

Trim then outfit one hull, leaving it OUTFITTED.

Both calls act as the context's AssemblyTechnician, so
`outfitted_by_technician_id` is that technician — which PRD.md
section 3.6 permanently bars from inspecting this hull.

#### `advance_unit_to_sellable(ctx: dict[str, Any], unit: dict[str, Any], *, trim_waste_kg: float=0.4, hardware_kit_serial: str | None = None, **inspect_overrides: Any) -> dict[str, Any]`

Trim, outfit and inspect one hull so it becomes SELLABLE.

The inspection is performed by the context's QualityInspector, who is
neither the cycle's operator nor the hull's outfitter, so segregation of
duties holds. The default readings clear every gate the default product
model declares, so the verdict is PASS, `final_warpage_index` is 0.000
and `build_status` becomes SELLABLE.

#### `setup_sellable_units(*, unit_count: int | None = None, **kwargs: Any) -> dict[str, Any]`

Take every hull of a demoulded cycle through to SELLABLE.

With `unit_count` set, only the first that many hulls are advanced and the
rest are left DEMOLDED, which is how a partially finished order is built.

Adds `sellable_units` and `sellable_unit_ids`, and refreshes
`production_order` — with the default mould and an `ordered_qty` of 2,
finishing both hulls moves the order to COMPLETE.

#### `setup_rework_unit(**kwargs: Any) -> dict[str, Any]`

Take one hull to REWORK through an adverse cosmetic grade.

A `cosmetic_defect_grade` of C reaches clause 7 of the verdict ladder in
PRD.md section 3.6, which yields REWORK, while the wall readings and impact
result still clear the earlier scrap clauses. The hull ends with
`build_status` REWORK, `inspection_verdict` REWORK and `rework_count`
1. Adds `rework_unit`.

#### `setup_scrapped_unit(**kwargs: Any) -> dict[str, Any]`

Take one hull to SCRAPPED through a rejected cosmetic grade.

A `cosmetic_defect_grade` of REJECT is clause 3 of the verdict ladder, so
the hull ends SCRAPPED with `inspection_verdict` SCRAP and the order's
`scrapped_qty` recomputed. Adds `scrapped_unit`.

#### `store_unit(ctx: dict[str, Any], unit: dict[str, Any]) -> dict[str, Any]`

Store one SELLABLE hull into the producing order's target warehouse.

The warehouse version is re-read immediately before the write. The server
chooses the zone; the first hull of a model in a zone becomes the nest
anchor and pays the model's full `gross_cube_m3`, and later hulls of the
same model pay `gross_cube_m3` times `nest_factor`.

#### `setup_stored_units(*, unit_count: int | None = None, **kwargs: Any) -> dict[str, Any]`

Store every SELLABLE hull of a finished cycle.

With the default mould, model and warehouse this stores two hulls into the
single zone: the first is the anchor at 2.0000 cube and the second nests at
1.0000 cube, leaving the site at 3.0000 committed cube of its 20.0000
capacity — 15.00 percent, posture NORMAL.

Adds `stored_units`, `stored_unit_ids` and a refreshed `warehouse`.

#### `setup_warehouse_at_posture(posture: str, **kwargs: Any) -> dict[str, Any]`

Store one hull into a site sized so its posture lands on `posture`.

One stored anchor hull of the default model commits exactly 2.0000 cube, so
the site capacity alone fixes the utilisation PRD.md section 3.7 derives:
20.0000 gives 10.00 percent and NORMAL, 2.2222 gives 90.00 percent and
RESTRICTED, and 2.0000 gives 100.00 percent and FROZEN.

Only one hull is stored, so the second hull of the cycle stays SELLABLE and
UNALLOCATED and is available as the next candidate — which is how a store
into a frozen site is exercised. Adds `stored_units` with one element.

#### `setup_build_ahead_bucket(*, forecast_qty: int=2, build_ahead_cap_pct: float=60.0, **kwargs: Any) -> dict[str, Any]`

Store hulls against a demand bucket so the build-ahead quota is in play.

The bucket's `build_ahead_cap_qty` is the floor of `forecast_qty` times
`build_ahead_cap_pct` over 100, so the defaults give a cap of 1: the first
hull stores and lands exactly on the cap, and a second store of the same
bucket is the request PRD.md refuses with ERR_BUILD_AHEAD_CAP_EXCEEDED.

The order names the bucket, so a stored hull copies `demand_bucket_id` and
counts toward `build_ahead_committed_qty`. Adds `demand_bucket`,
`demand_bucket_id` and stores exactly one hull.

#### `setup_mold_due_for_service(**kwargs: Any) -> dict[str, Any]`

Run enough cycles that the mould's service counter reaches its interval.

`service_interval_cycles` is set to 1, so the single demoulded cycle
leaves `cycles_since_service` at 1 and the mould in MAINTENANCE — the
counter comparison in PRD.md triggers at or above the interval. A further
cycle on that mould is the request the service rule refuses.

Adds a refreshed `mold`.

#### `setup_depleted_resin_lot(**kwargs: Any) -> dict[str, Any]`

Charge a lot whose `received_kg` exactly covers one shot.

The lot receives 24.000 kg, the mould's full shot mass, so reserving one
charge moves the whole ledger into `reserved_kg` and leaves
`available_kg` at 0.000 with the conserved sum intact.

Adds a refreshed `resin_lot`.

#### `setup_expired_resin_lot(*, expires_on: str='2026-08-05', expiry_clock: str='2026-08-06T00:00:00Z', **kwargs: Any) -> dict[str, Any]`

Reserve a charge, then move the clock past the lot's expiry date.

PRD.md section 2.5 makes setting the clock an active sweep: a lot whose
`expires_on` calendar date now lies strictly before the clock's date is
expired, and the cascade releases its reserved charges, aborts the cycles
that depended on them and blocks the affected orders.

Adds `clock_result` with the four sweep counters the call reported, plus
refreshed `resin_lot`, `resin_charge`, `molding_cycle` and
`production_order`.

#### `create_shipment(ctx: dict[str, Any], **overrides: Any) -> dict[str, Any]`

Book a PLANNED trailer out of the context's warehouse.

The default trailer holds 5.0000 cube and 200.000 kg. Two hulls of the
default model nest to 3.0000 cube, which is exactly the 60.00 percent
utilisation PRD.md section 3.8 sets as the minimum for sealing, and selects
the 3.00 percent volume discount tier.

#### `load_unit(ctx: dict[str, Any], shipment: dict[str, Any], unit: dict[str, Any], **overrides: Any) -> dict[str, Any]`

Add one STORED hull to a trailer as a LOADED line.

The shipment version is re-read immediately before the write. The hull moves
STORED to LOADED without any footprint movement, and the first line on a
PLANNED trailer moves it to LOADING.

#### `setup_loaded_shipment(*, line_count: int | None = None, shipment_overrides: dict[str, Any] | None = None, **kwargs: Any) -> dict[str, Any]`

Store the cycle's hulls, book a trailer and load them all onto it.

On return the shipment is LOADING with one LOADED line per hull, each hull
LOADED but still occupying its warehouse zone, and the rollups recomputed:
with the two default hulls that is `loaded_cube_m3` 4.0000,
`nested_cube_m3` 3.0000, `loaded_weight_kg` 48.000 and
`cube_utilization_pct` 60.00.

Adds `shipment`, `shipment_id`, `shipment_lines` and
`shipment_line_ids`.

#### `setup_sealed_shipment(**kwargs: Any) -> dict[str, Any]`

Seal a loaded trailer, which prices the QUOTED freight variant.

Sealing requires LOADING, at least one line and a `cube_utilization_pct`
at or above 60.00. On return the shipment is SEALED with
`quoted_freight_cents` set and `sealed_at` stamped from the clock, and
`billed_freight_cents` still null.

#### `setup_departed_shipment(*, departed_at: str=DEFAULT_DEPART_AT, **kwargs: Any) -> dict[str, Any]`

Dispatch a sealed trailer, which frees the hulls' warehouse footprint.

The clock is set to `departed_at` before the stamp. On return the shipment
is IN_TRANSIT, every hull is IN_TRANSIT with its `storage_zone_code`,
`stored_at` and `demand_bucket_id` cleared and its
`stored_footprint_cube_m3` zeroed, and the origin site's committed cube,
utilisation and posture have been recomputed downward.

Adds a refreshed `warehouse`.

#### `setup_delivered_units(*, delivered_at: str=DEFAULT_DELIVER_AT, **kwargs: Any) -> dict[str, Any]`

Deliver a departed trailer, which starts each hull's warranty clock.

The clock is set to `delivered_at` before the stamp, so every hull's own
`delivered_at` — the origin of the warranty clock — is that instant. On
return the shipment is DELIVERED with `billed_freight_cents` set from the
gross-cube BILLED variant, and every hull is DELIVERED with
`warehouse_id` cleared.

Adds `delivered_units` and `delivered_unit_ids`.

#### `setup_delivered_unit_with_customer(*, acknowledged_at: str=CLOCK_DEFAULT_UTC, delivered_at: str=DEFAULT_DELIVER_AT, **kwargs: Any) -> dict[str, Any]`

Deliver hulls and register a customer who acknowledged storage guidance.

The acknowledgement is dated on the clock's startup default, well before
`delivered_at`, which is what a VERIFIED storage review requires in
PRD.md section 3.9.

Adds `customer`, `customer_id`, `customer_headers` and `unit` — the
first delivered hull, the one the claim ladder files against.

#### `setup_submitted_claim(**kwargs: Any) -> dict[str, Any]`

File one claim against a delivered hull.

The claim is a HULL_DEFORMATION claim whose `reported_deformation_mm` of
4.50 clears the 3.00 mm threshold. It starts SUBMITTED with
`storage_review_status` NOT_STARTED, no money fields set and version 1.

Adds `warranty_claim` and `warranty_claim_id`.

#### `setup_claim_under_review(**kwargs: Any) -> dict[str, Any]`

Move a submitted claim into review, which freezes its age.

Starting review computes `months_in_service` as the complete calendar
months from the hull's `delivered_at` to the clock, floored. With the
ladder's default instants the clock still stands at delivery, so the frozen
age is 0 months and a PRO_RATA_AGE model covers 100.00 percent.

#### `setup_claim_storage_verified(**kwargs: Any) -> dict[str, Any]`

Decide the storage axis as VERIFIED on a claim under review.

VERIFIED requires the customer's `storage_guidance_acknowledged_at` to be
non-null and at or before the hull's `delivered_at`, which the ladder's
customer satisfies. The axis becomes GUIDANCE_VERIFIED, the adjudication
axis stays UNDER_REVIEW, and the eventual approval carries a zero storage
deduction.

#### `setup_claim_storage_violated(**kwargs: Any) -> dict[str, Any]`

Decide the storage axis as VIOLATED on a claim under review.

The axis becomes GUIDANCE_VIOLATED, which blocks approval until a
PlantAdmin waives the finding, and forces a denial's `denial_reason` to
STORAGE_GUIDANCE_VIOLATED whatever the request body asks for.

#### `setup_claim_storage_waived(**kwargs: Any) -> dict[str, Any]`

Waive a violated storage finding, which unblocks approval at a cost.

The axis becomes WAIVED. A claim approved from WAIVED still pays the
35.00 percent storage deduction, so this is the fixture that separates a
waiver from a clean VERIFIED review.

#### `setup_approved_claim(*, waived: bool=False, **kwargs: Any) -> dict[str, Any]`

Approve a claim, which is the only path that spends the reserve.

With `waived` false the claim is approved from GUIDANCE_VERIFIED and the
storage deduction is 0; with `waived` true it is approved from WAIVED and
the 35.00 percent deduction applies. The model's version is re-read
immediately before the write, so `expected_product_model_version` is
current.

On return the claim is APPROVED with all four money fields set and
`payout_basis` copied from the model, and the model's reserve has moved:
`warranty_reserve_cents` down and `warranty_paid_cents` up by the
identical `net_payout_cents`.

Adds a refreshed `product_model`.

#### `setup_denied_claim(*, denial_reason: str='NOT_A_MANUFACTURING_DEFECT', **kwargs: Any) -> dict[str, Any]`

Deny a claim whose storage axis has been decided.

Denial requires the storage axis to be anything but NOT_STARTED. On return
the claim is DENIED with all four money fields set to an explicit 0 and no
reserve movement.

#### `overlapping_window(cycle: dict[str, Any], *, start_offset_minutes: int=0, oven_minutes: int | None = None) -> dict[str, Any]`

Cycle-creation overrides whose oven window sits beside `cycle`'s.

`start_offset_minutes` is measured from the stored cycle's
`oven_start_at`, so 0 reproduces it exactly, a negative value starts
earlier and a positive value starts later. PRD.md section 3.4 treats the
oven window as half-open, so an offset equal to the stored cycle's oven
duration abuts without overlapping unless the station's changeover buffer
pushes the two apart. `oven_minutes` overrides the new cycle's own oven
duration; by default it matches the stored cycle's.

#### `setup_cycle_with_spare_order(**kwargs: Any) -> dict[str, Any]`

A SCHEDULED cycle plus a second released order ready to schedule.

Builds `setup_scheduled_cycle` and then adds one more ResinLot and one
more ProductionOrder released to READY_TO_SCHEDULE against the same model,
warehouse, station and cooling bay. Nothing is scheduled for the second
order, so a test can attempt its own cycle — overlapping, abutting or on
another arm — and observe the resource rules of PRD.md section 3.4.

Adds `spare_production_order`/`spare_production_order_id` and
`spare_resin_lot`/`spare_resin_lot_id` to the context.

#### `setup_cooling_bay_at_capacity(**kwargs: Any) -> dict[str, Any]`

A cooling bay whose single concurrent slot is already taken.

Same shape as `setup_cycle_with_spare_order` but the bay is created with
`concurrent_slot_capacity` 1, so the stored SCHEDULED cycle already
occupies the bay for its whole closed cooling interval and any second cycle
overlapping that interval must be refused.

#### `setup_station_down(**kwargs: Any) -> dict[str, Any]`

A SCHEDULED cycle whose oven station has since been marked DOWN.

Marks the context's station DOWN after the cycle is stored, which PRD.md
section 3.4 says leaves the cycle in place while blocking any further
scheduling on that station. Refreshes `oven_station` and
`molding_cycle` and adds `down_reason`.

#### `setup_mold_on_service_hold(**kwargs: Any) -> dict[str, Any]`

A plant baseline whose only mould is in MAINTENANCE.

Places the mould on service hold straight from AVAILABLE, so scheduling a
cycle for its product model has no usable mould. Refreshes `mold` and
adds `hold_note`.

#### `setup_quarantined_lot_with_charge(**kwargs: Any) -> dict[str, Any]`

A SCHEDULED cycle whose reserved lot has since been QUARANTINED.

Builds the charge first and then quarantines the lot, which is the
precondition PRD.md section 3.2 describes for the quarantine cascade: the
lot leaves AVAILABLE while its reserved mass is accounted for. Quarantine
carries no version declaration, so nothing is re-read before the write.
Refreshes `resin_lot`, `resin_charge` and `molding_cycle` and adds
`quarantine_reason`.


---

## 9. Context keys

A context is a flat `dict`. These are all the keys any helper in this package ever
sets, together with the rung that adds them. Higher rungs never remove a key, so a
context from `setup_approved_claim` still carries `product_model_id`.

| Key | Added by | Value |
|---|---|---|
| `clock` | `create_plant_baseline` | the instant the clock was set to, or `None` |
| `admin_headers`, `planner_headers`, `agent_headers` | `create_plant_baseline` | the three opaque role header dicts |
| `product_model`, `product_model_id` | `create_plant_baseline` | ProductModel row and id |
| `mold`, `mold_id` | `create_plant_baseline` | Mold row (AVAILABLE, `cycles_since_service` 0) and id |
| `oven_station`, `oven_station_id` | `create_plant_baseline` | OvenStation row (OPERATIONAL) and id |
| `cooling_bay`, `cooling_bay_id` | `create_plant_baseline` | CoolingBay row (OPERATIONAL) and id |
| `warehouse`, `warehouse_id` | `create_plant_baseline` | Warehouse row (NORMAL, zero committed cube) and id |
| `resin_technician`, `resin_technician_id`, `resin_tech_headers` | `create_plant_baseline` | ACTIVE `RESIN_TECH` Technician |
| `molding_operator`, `molding_operator_id`, `operator_headers` | `create_plant_baseline` | ACTIVE `MOLDING_OPERATOR` Technician |
| `assembly_technician`, `assembly_technician_id`, `assembly_headers` | `create_plant_baseline` | ACTIVE `ASSEMBLY_TECH` Technician |
| `quality_inspector`, `quality_inspector_id`, `inspector_headers` | `create_plant_baseline` | ACTIVE `QUALITY_INSPECTOR` Technician |
| `resin_lot`, `resin_lot_id` | `setup_scheduled_cycle` | qualified ResinLot |
| `production_order`, `production_order_id` | `setup_scheduled_cycle` | ProductionOrder, READY_TO_SCHEDULE by default |
| `molding_cycle`, `molding_cycle_id` | `setup_scheduled_cycle` | MoldingCycle, refreshed by every later rung |
| `resin_charge`, `resin_charge_id` | `setup_scheduled_cycle` | ResinCharge, or `None` when `charge=False` |
| `units` | `setup_demolded_units` and above | list of FinishedUnit rows for the cycle, refreshed by each rung |
| `unit`, `unit_id` | `setup_rework_unit`, `setup_scrapped_unit`, `setup_delivered_unit_with_customer` | the single hull the helper is about |
| `demand_bucket`, `demand_bucket_id` | `setup_build_ahead_bucket` | DemandForecastBucket covering the clock's date |
| `shipment`, `shipment_id` | `setup_loaded_shipment` and above | Shipment, refreshed by each rung |
| `shipment_lines` | `setup_loaded_shipment` and above | list of ShipmentLine rows, one per loaded hull |
| `customer`, `customer_id`, `customer_headers` | `setup_delivered_unit_with_customer` | ACTIVE Customer holding the headers for the Customer role |
| `warranty_claim`, `warranty_claim_id` | `setup_submitted_claim` and above | WarrantyClaim, refreshed by each rung |
| `spare_production_order`, `spare_production_order_id`, `spare_resin_lot`, `spare_resin_lot_id` | `setup_cycle_with_spare_order` | a second released order and lot with nothing scheduled |
| `down_reason`, `hold_note`, `quarantine_reason` | the matching cascade helper | the reason string that was sent |

---

## 10. `test_suite/conftest.py`

This package deliberately contains no `conftest.py`. Use this content so every test
file agrees on fixture names:

```python
"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import ApiClient, api_client, ADMIN_HEADERS, PLANNER_HEADERS, AGENT_HEADERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client; server lifecycle is the runner's job."""
    return api_client


@pytest.fixture
def admin_headers() -> dict[str, str]:
    return ADMIN_HEADERS


@pytest.fixture
def planner_headers() -> dict[str, str]:
    return PLANNER_HEADERS


@pytest.fixture
def agent_headers() -> dict[str, str]:
    return AGENT_HEADERS
```

The four shop-floor roles and the Customer role get no conftest fixture, because
their headers must reference a row that this test created — take them from a
context or call `create_technician` / `create_customer`.

---

## 11. Numbers the default ladder lands on

These follow from the factory defaults and are worth knowing before writing an
assertion, because several sit exactly on a threshold boundary.

* **Mould shot mass.** The model's `nominal_charge_kg` is 12.0 for one cavity and the
  default mould has `cavity_count` 2, so its shot mass is 24.0 kg. The default charge
  is `charge_kg` 24.0 with `regrind_kg` 2.4, i.e. `charge_regrind_pct` 10.00 against
  the model's ceiling of 30.00, and a deviation of 0 % against a tolerance of 5.00.
  Two hulls come out of every cycle.
* **Resin lot.** 500.0 kg received, melt index 4.00 inside the model's 2.50–6.00 band,
  and `expires_on` 2027-12-31, so moving the clock anywhere inside 2026 does not
  expire it. `setup_expired_resin_lot` overrides both the expiry and the clock.
* **Cycle window.** `oven_start_at` 09:00, 60 scheduled oven minutes, 30 scheduled
  cooling minutes, so `oven_end_at` is 10:00 and `cooling_window_end_at` is 10:30.
  The ladder demoulds at 10:35, giving `actual_cooling_minutes` 35, which clears the
  model's `min_cooling_minutes` of 30.
* **Inspection.** The default readings `[5.9, 6.0, 6.1, 5.95, 6.05, 6.0]` are six
  points — exactly the minimum — with a mean of 6.000 and a coefficient of variation
  well inside the model's `wall_cv_max_pct`, an impact result above the model's
  minimum, and cosmetic grade `A`, so the verdict is PASS. Cosmetic grade `C` gives
  REWORK and `REJECT` gives SCRAP deterministically, which is how
  `setup_rework_unit` and `setup_scrapped_unit` work.
* **Storage cube.** The model's `gross_cube_m3` is 2.0 and its `nest_factor` 0.5, so
  a zone anchor commits 2.0000 and each follower commits 1.0000.
* **Posture.** `setup_warehouse_at_posture` uses site capacities 20.0, 2.2222 and 2.0
  against one stored anchor, landing on 10.00 % (NORMAL), 90.00 % (RESTRICTED, on the
  boundary) and 100.00 % (FROZEN).
* **Build-ahead quota.** `setup_build_ahead_bucket` defaults to `forecast_qty` 2 and
  `build_ahead_cap_pct` 60.0, which floors to a cap of 1: the first store lands
  exactly on the cap and a second store is the refusal case.
* **Freight.** Two default hulls nest to 3.0000 m3 in a 5.0 m3 trailer, i.e. exactly
  60.00 % utilisation — exactly the seal minimum and exactly on the lowest discount
  tier boundary. If a test needs to be off the boundary, pass
  `shipment_overrides={"trailer_cube_capacity_m3": 4.0}` or load a third hull.
* **Warranty.** The model's `warranty_basis` is `PRO_RATA_AGE`. A claim filed on the
  ladder's default delivered hull has `months_in_service` 0, so coverage is
  100.00 % and, with a `HULL_DEFORMATION` factor of 1.00: gross 180000 cents, admin
  fee 8.00 % = 14400, no storage deduction when the review is VERIFIED, net 165600
  against an initial reserve of 500000. A WAIVED review deducts 35.00 % instead.

---

## 12. Places PRD.md is ambiguous

Where PRD.md contradicts itself, this package takes the reading below and keeps its
assertions lenient so a defensible implementation is not failed for the wrong reason.
Tests should do the same rather than asserting the stricter reading.

1. **`ResinCharge.created_by_technician_id` and `MoldingCycle.operator_technician_id`**
   are described as client-supplied in the field reference but as "the acting
   identifier" in the workflow text, and neither endpoint lists them as input. The
   factories omit both by default and expose them as overrides, which is what the
   identity-mismatch cases need.
2. **`Shipment` has no `customer_id`.** The trailer workflow talks about booking
   against one customer and about requiring that customer to be ACTIVE, but neither
   the entity nor `POST /shipments` has such a field. `shipment_payload` omits it;
   the ACTIVE precondition is not reachable as specified.
3. **Warpage index scale.** Treat it as three decimals clamped to 0.000–5.000, which
   is what the finishing workflow specifies; `assert_warpage_index_shape` checks that.
4. **`min_wall_thickness_mm`, `density_kg_per_m3`.** The field reference says two
   decimals, the workflow text says three. Assert the value, not the number of
   decimals.
5. **`unit_cost_cents`, `months_in_service`, `build_ahead_cap_qty`.** Each has a
   default of 0 in the field reference but is described as null (or as at least 1) in
   the workflow text. Accept either — `assert_null_fields` is deliberately not applied
   to these.
6. **`departed_at` / `delivered_at`.** The prose says the server stamps them from the
   clock; the endpoint inputs carry them. The client sends them and the fixtures set
   the clock to the same instant, so both readings agree.
7. **Clock sweep counters.** The read endpoint is described as reporting the four
   cascade counters, but the output schema puts them only on the write. Treat them as
   optional on a read and assert them on the response to `set_current_utc`.
