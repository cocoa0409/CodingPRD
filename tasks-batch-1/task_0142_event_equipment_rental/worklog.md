# Worklog — task_0142_event_equipment_rental

## Step 1: Create task directory — 2026-06-04T02:04:57.000Z

Created `tasks/task_0142_event_equipment_rental/` and `tasks/task_0142_event_equipment_rental/workspace/` at the pre-allocated index 0142 (no scan / no auto-increment, per orchestration override). Scenario: Event & Party Equipment Rental. Target Expert difficulty.

## Step 2: Generate scaffold (Expert) — 2026-06-04T02:24:10.000Z

The scaffold for **task_0142_event_equipment_rental** (Expert difficulty) is complete and lint-clean.

Files generated (all lint-clean — `VERDICT: clean lint`): SCAFFOLD.yaml (1133 lines), SCAFFOLD_DIFFICULTY_DESIGN.yaml (1008 lines), SCAFFOLD_CORNER_DESIGN.yaml (1395 lines).

**Complexity profile**: primary archetype temporal_windowing + secondary quota_allocation; flat topology; parallel state-machine shape; peer_roles (with segregation of duties); immediate consistency. Layers: optimistic_concurrency, cascading_side_effects, dual_variant_calculation, rate_threshold_triggers. `api_prefix: ""` (flat collections; required so FK reverse-reachability resolves).

**Entities (10)**: CatalogItem, Customer, Venue, InsuranceCertificate, RentalOrder, OrderLine, DeliveryRun, Crew, DepositLedgerEntry (append-only, common_fields:false), WeatherEvent (common_fields:false).

**State machines (5)**: CatalogItem.status (ACTIVE→RETIRED); RentalOrder.booking_status (DRAFT→CONFIRMED→FULFILLED→RETURNED, +CANCELLED) × RentalOrder.settlement_status (UNSETTLED→DEPOSIT_HELD→{RELEASED|FORFEITED}) as parallel dimensions; InsuranceCertificate.status (SUBMITTED→APPROVED→REVOKED, +REJECTED); DeliveryRun.status (cyclic SCHEDULED↔ATTEMPTED, +COMPLETED/CANCELLED).

**Calculations (7)**: line_rental_charge (multi-day, round-then-multiply pinned), order_rental_subtotal, delivery_fee (zone base + unit surcharge + subtotal waiver), weather_refund_amount (CONFIRMED-full vs FULFILLED-deposit-only variants), customer_account_credit, deposit_held_balance (chronological replay), venue_coi_status (closed-inclusive coverage projection).

**Validations**: 20 ordered rules. **Endpoints**: 40 (above the Expert ceiling of 32, driven by mandatory FK reverse-reachability GETs and the rich action surface — kept since each is test-exercised and lint is clean). **Error catalog**: 21. **Concurrency rules**: 2 OCC (confirm + deposit-settle, both 412 on `expected_order_version`). **Roles (3)**: Customer (entity_backed), RentalAgent (opaque), DepositAdjuster (opaque, segregated from RentalAgent for deposit settlement).

**Difficulty design**: 18 instances — exactly 2 per each of the 9 Difficulty Rules. **Corner design**: 43 instances total — 38 active + 5 `excluded_because` stubs (all citing valid §1.8 instances), spanning all 9 claim-extraction sections.

**Key fixes during generation**: (1) bracketed `grounds:` tokens broke YAML in flow sequences → quoted them; (2) initial FK_REVERSE_UNREACHABLE wall → set `api_prefix: ""` and renamed sub-resource parent-id path segments to `{id}`; (3) removed dead enum values (`Crew.status` OFF_DUTY) and turned the unreachable `RETIRED`/`ERR_INACTIVE_ITEM` corner into a real test by adding `POST /catalog-items/{id}/retire` + CatalogItem state machine.

## Step 3: Copy INSTRUCTION.md — 2026-06-04T02:24:31.000Z

Copied `./INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-04T02:30:51.000Z

Generated `workspace/PRD.md` (295 lines, 5 top-level sections; §2 has 12 subsections, §3 has 9 subsections).

**Notable coverage decisions:**
- §3 organized as a business-process timeline (catalog/yard setup → customers/venues/COI → draft assembly & pricing → confirm → fulfill/return/cancel → deliveries → ledger/credit → settlement → weather cancel).
- The two parallel order status dimensions (`booking_status` × `settlement_status`) introduced together in §2.6, then woven through §3.
- Multi-day rental pricing renders pinned round-then-multiply order explicitly (per-unit rounded half-up first, then × quantity).
- Delivery-fee thresholds as prose with exact boundaries (zone bases 5000/9000/15000 cents; 4000-cent surcharge at ≥100 units; base waiver at ≥200000-cent subtotal, surcharge never waived).
- Both OCC rules (confirm + deposit-settle) framed in stale-version terms with `expected_order_version`/`version`/`ERR_STALE_VERSION`/412.
- Weather-refund CONFIRMED-vs-FULFILLED branches and FORFEIT-with-remainder cascade given equal specification density.
- Added computed availability fields (`reserved_units`, `available_units`) to §2.7 and `ERR_VALIDATION` mention to §2.1.

**Hard Contract Reports:** Field coverage PASS (58/58 entity fields, 11/11 endpoint inputs); Rule coverage PASS (20 validations, 2 OCC, all state-machine transitions, 7 calculations, sibling-branch symmetry all rendered); Path purity PASS (§4 table = 40 endpoints/4 cols; §5 = 21 errors/2 cols; 0 path/method leaks in §3). Design files NOT read.

## Step 5: Generate unit tests — 2026-06-04T03:01:49.000Z

Generation complete. All infrastructure written, parses, collects under pytest, passes the full coverage/citation audit.

**test_helpers/ (Stage 1) — 9 files**: `__init__.py`, `types.py` (entity TypedDicts + status/role enums; DepositLedgerEntry & WeatherEvent carry only id+created_at as append-only), `api_client.py` (one method per endpoint), `api_errors.py` (21 error IDs + HTTP-status map), `assertions.py` (per-entity assertions + `compute_held_balance` ledger-replay helper), `factories.py` (input-field-only payloads), `constants.py` (delivery-fee thresholds), `test_users.py` (opaque RentalAgent/DepositAdjuster constants + `make_customer_headers` per-instance builder for entity_backed:Customer), `fixtures.py` (composite setup helpers).

**test_suite/ (Stage 2) — 8 files** (conftest.py + 7 test files). **Total: 74 tests.**
- **Queue A (Difficulty): 36 tests** — all 18 difficulty instances covered by ≥2 tests each (9 rules × 2 instances).
- **Queue B (Corner): 38 tests** — every one of the 38 non-stub corner instances covered by ≥1 test.

**Skipped instances: 4** — the `excluded_because` stubs in the corner index (spec forbids translating; cited difficulty instance owns the assertion). All 4 stub cross-refs resolve to real difficulty instances. No instances skipped under the PRD-first filter — every non-stub instance had verbatim, uniquely-derivable PRD coverage.

**Audit (all green):** 96/96 docstring citations match PRD.md verbatim; every docstring ends with exactly one resolvable Design: tag; no scaffold/section leakage; all 74 tests collect cleanly.

Note: this task's scaffold/PRD use `ERR_VALIDATION` (not the skill template's `ERR_INVALID_REQUEST`) for malformed requests — error catalog and tests use `ERR_VALIDATION` consistently.

## Step 6: Generate implementation — 2026-06-04T03:01:49.000Z

Built complete Python + Flask implementation in `workspace/implementation/`.

**Files (10):** `start.sh` (foreground launcher, guarded pip install `if ! python3 -c "import flask"`, reads $PORT default 10000, binds 0.0.0.0, `exec python3 app.py`), `app.py` (40 routes + validation orchestration + state machines + cascades + error handlers), `calculations.py` (multi-day pricing, delivery fee, held-balance replay, Decimal/ROUND_HALF_UP), `db.py` (in-memory Store, dicts keyed by id, UUID/timestamp helpers, monotonic seq; **no seeding**), `errors.py`, `response.py`, `middleware.py`, `serializers.py`, `timeutil.py`, `requirements.txt`.

**Endpoints: 40** (exactly scaffold §1.5 / PRD §4 table).

**Structure:** module-level `store` singleton rebuilt empty on every boot; internal `_`-prefixed fields stripped by serializers. OCC via `expected_order_version` on confirm/cancel/deposit-settle → ERR_STALE_VERSION (412), checked last (priority 18); `version` bumps +1 on every mutation incl. cascades via single `touch()`. Round-then-multiply pinned; delivery fee zone base + ≥100-unit surcharge + ≥200000-cent base waiver (surcharge never waived); held-balance/account_credit by forward replay created_at ASC (tie-break insertion seq, never id). Boundaries verified exact (99/100 units, 199999/200000 subtotal, 333×0.9→300 half-up).

**PRD ambiguities resolved (flag for Step 7/8/9):**
1. **COI gate vs WILL_CALL** — COI required per-line by item, not by fulfillment; a WILL_CALL order with a TENT/BOUNCE_HOUSE (requires_coi) still needs a covered venue.
2. **Double-settle precedence** — PRD frames double-settle as OCC stale-version, but first settle moves settlement_status to terminal, so state check (priority 5) fires before OCC (priority 18) → ERR_INVALID_STATE. Priority ordering kept authoritative.
3. **Reject/revoke `reason`** — InsuranceCertificate has no `reason` field; optional `reason` input accepted but not persisted.
4. **Weather-event zone match for WILL_CALL** — WILL_CALL orders have no venue/zone; WARNING match requires only effective_date in event window (zone filter skipped when order has no zone).

## Step 7: Run tests and iterate — 2026-06-04T03:08:23.000Z

All 8 rounds passed 74/74. Clean sweep.

**Iterations run:** 2 (initial sweep diagnosed 1 failure; second sweep confirmed the fix across all 8 rounds).

**Tests deleted:** None. No PRD-silence or unique-derivability collapse was found.

**Fixes applied to `test_helpers/`:** None.

**Fixes applied to `implementation/`:** None.

**Fix applied to `test_suite/`:**
- `test_suite/test_07_validations_rbac_errors.py` — `test_order_version_increments_on_add_line`: the assertion read `line["version"]` from the `POST /orders/{id}/lines` response. That endpoint returns the newly-created `OrderLine` (standard 201 Created), and a fresh OrderLine carries its own `version == 1` (PRD §2.4 line 92 says OrderLine carries a version). The PRD rule under test ("Each line addition ... increments the order's `version` by one", PRD §2.4 line 94 / §3.2 line 166) is a property of the **RentalOrder**, not the line response body. The test was reading the wrong object. Fixed it to re-fetch the order via `GET /orders/{id}` and assert the **order's** version is 2 after one add_line. This STEP 2 fix makes the test strictly more faithful to PRD. PRD nowhere states add_line returns the order, so the implementation (returning the line) is PRD-faithful and required no change.

**Diagnostic notes:** The Step 6 implementer's four flagged ambiguities (double-settle precedence ERR_INVALID_STATE vs ERR_STALE_VERSION, COI-gate-vs-WILL_CALL, reject/revoke `reason` non-persistence, weather-event zone matching) caused no test friction — all related tests passed in every round. No pip/bind-race/keep-alive flakiness observed; the single failure was deterministic across all 8 rounds.

**Final sweep:** All 8 parallel rounds passed == total at **74/74**.

## Step 8: Finalize PRD — 2026-06-04T03:13:30.000Z

Produced `workspace/PRD_FINALIZED.md`. Both 295 lines; one line (§3.3, line 166) revised in place; 0 lines added/removed (0.0% line delta).

**Change:**
- §3.3 (Assembling and Pricing a Draft Order) — insert — Pinned that `POST /orders/{id}/lines` returns the newly-created `OrderLine` object (HTTP 201) with its own `version` of 1, not the updated parent order — even though adding a line both creates the line and mutates the order's version. `implementation/app.py:805` (`return success_object(ser.line_view(rec), 201)`); shape from `serializers.py:60-66` + `stamp_created` `app.py:176-184` setting `version=1`.

**Rationale:** The lone Step 7 fix was test-side (`test_order_version_increments_on_add_line` read `line["version"]` expecting the order's version). PRD §2.2 says create/modify operations return "the created or updated resource object," but adding a line both *creates* an OrderLine and *updates* the order — prose did not uniquely determine which lands in `data`. Impl pins it to the created OrderLine. Genuine PRD silence, now pinned.

**Pre-edit search log:** (a) subject = response `data` of `POST /orders/{id}/lines` + created line's version. (b) enumerated: `add_line` app.py:776-805 (returns line_view at 201, order touched not returned), `remove_line` app.py:821-835 (returns line_view at 200), `line_view` serializers.py:60-66, `stamp_created` app.py:176-184 (version=1), `touch` app.py:169-173, all order-transition endpoints app.py:932-1103 (return order_view). (c) scoped sentence strictly to add-line ("the add-line operation's response `data`", "not the updated order") so it makes no claim about remove_line or transitions and cannot over-generalize §2.2.

The four Step 6 flagged ambiguities caused no test friction and are out of Step 8's HARD SCOPE.

## Step 9: Complete PRD — 2026-06-04T03:17:51.000Z

Produced `workspace/PRD_COMPLETED.md`. Source `PRD_FINALIZED.md` (295 lines, 46,264 chars) → `PRD_COMPLETED.md` (295 lines, 48,047 chars). Char delta +1,783; line count unchanged (all edits in-paragraph).

**Counts:** ambiguity-pins = 3 (one also folds in an extra genuine silence), mismatch-revisions = 1. Total 4 edited paragraphs.

**Per-change:**
- §2.11 (Optimistic Concurrency Control) — revise — mismatch — PRD claimed a second deposit settlement returns `ERR_STALE_VERSION`; impl returns `ERR_INVALID_STATE` because the settlement-status state check (settlement_status != DEPOSIT_HELD) runs before the OCC version check, and the first settle moves settlement to a terminal state — `app.py:1076` (state check) before `:1089` (OCC check).
- §3.2 (Certificates of Insurance) — insert — ambiguity — reject/revoke "may carry an optional `reason`" was silent on persistence; pinned `reason` is accepted but not persisted (no `reason` field on InsuranceCertificate, never returned) — `app.py:677,691`, `serializers.py:42-47`.
- §3.4 (Confirming an Order) — insert — ambiguity — pinned that the COI gate is per-line by `requires_coi` regardless of fulfillment mode; a WILL_CALL order containing any `requires_coi` line always fails `ERR_COI_REQUIRED` (no venue → never VALID) — `app.py:896-903`.
- §3.9 (Weather Cancellation) — insert — ambiguity — (a) `delivery_zone` matching: DELIVERY matches the venue's zone, WILL_CALL skips the zone filter (`app.py:1016-1030`); (b) folded-in silence: weather-cancel permitted only from CONFIRMED/FULFILLED, else ERR_INVALID_STATE, checked before the matching-event check (`app.py:1012-1013` before `:1031-1032`).

Pipeline complete: all 9 steps done; final 8-round sweep green at 74/74.
