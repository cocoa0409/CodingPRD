# Worklog — task_1662_printed_circuit_board_fabrication

## Step 1: Create Task Directory — 2026-08-14T05:51:00.000Z

Directory `tasks/task_1662_printed_circuit_board_fabrication/` and its `workspace/` subdirectory were pre-created and pre-assigned by the pipeline dispatcher. Step 1 treated as DONE per instructions; no index scan performed, no other task_* directory touched.

## Step 3: Copy Shared Files — 2026-08-14T05:52:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_1662_printed_circuit_board_fabrication/workspace/INSTRUCTION.md`.

## Step 2: Generate Scaffold — 2026-08-14T06:45:00.000Z

Scaffold generation complete. All three artifacts are written and pass the skill's mechanical linter with a clean verdict (986 test-recipe calls validated against §1.5; all 16 FKs reverse-reachable), plus my extended audits: instance names unique across both design files, every `grounds:` reference resolves, all 36 error codes are referenced by a validation or transition, endpoint roles ⊆ RBAC roles, no forbidden concurrency vocabulary, and both OCC rules satisfy the hard constraints.

**Design summary** (PCB bare-board fabrication, `/pcb` prefix):

- **Entities: 16** — Customer, QuickTurnLane, LaminateLot, FabOrder, Stackup, ImpedanceSpecLine, PanelArray, DrillProgram, LaminateReservation (many-to-many junction), LaneSlotCommitment, ImpedanceCoupon, CouponMeasurement (append-only), LabSlotBooking, ElecTestRun, DefectRecord (append-only), Invoice
- **State machines: 11** — FabOrder carries two parallel dimensions (fab_status pipeline × quality_disposition), cyclic DrillProgram review loop and ImpedanceCoupon retest loop, plus Stackup/PanelArray supersede, LaminateLot expiry, Reservation, LabSlotBooking, ElecTestRun, Invoice machines
- **Calculations: 8** — panel yield (nested max/floor/ceil), order pricing with pinned per-line-then-sum rounding and PROVISIONAL/FINAL variants, impedance disposition with SINGLE/STATISTICAL variants, aspect-ratio ceiling, date-code window, lane capacity, defect Pareto, credit check
- **Validations: 36** ordered priorities (auth → existence → ownership → SoD → state → safety → temporal → constraint → fiscal → OCC)
- **Endpoints: 73** (incl. `POST /pcb/_clock/set_current_utc` with the mandatory 2026-08-01T00:00:00Z default)
- **Errors: 36**; **Roles: 7** (Customer entity-backed; 6 opaque internal roles with segregation-of-duties on drill approval)
- **§1.8: 20 non-stub instances** (≥2 per rule; non_linear_state_machine and transitive_cascade have 3 each) — all numeric asserts pre-computed (e.g., provisional 68248 vs final 73615, rounding trap 2343 vs 2344, Pareto cumulative 37.50/62.50/87.50/100.00, aspect ratio 8.0 pass vs 8.857 fail)
- **§1.9: 58 non-stub instances + 22 `excluded_because:` stubs** across all nine claim-extraction sections

Files written:
- `/home/ubuntu/github/CodingPRD/tasks/task_1662_printed_circuit_board_fabrication/SCAFFOLD.yaml`
- `/home/ubuntu/github/CodingPRD/tasks/task_1662_printed_circuit_board_fabrication/SCAFFOLD_DIFFICULTY_DESIGN.yaml`
- `/home/ubuntu/github/CodingPRD/tasks/task_1662_printed_circuit_board_fabrication/SCAFFOLD_CORNER_DESIGN.yaml`

Lint verdict (verbatim): `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` One FK violation (CouponMeasurement→LabSlotBooking) was found and fixed during iteration by adding `GET /pcb/lab-slot-bookings/{id}/measurements`; no sibling tasks were consulted at any point.

## Step 4: Generate PRD — 2026-08-14T06:58:00.000Z

Both "around" hits are structural ("organized around", "Around the order sit") — not numeric approximations, so they don't violate the no-fuzzy-words rule. All contracts pass. Final verification summary is complete.

## Summary

**Output written:** `/home/ubuntu/github/CodingPRD/tasks/task_1662_printed_circuit_board_fabrication/workspace/PRD.md`

**Line count:** 325 lines

**Section list:**
- §1 Introduction (2 paragraphs, business-context angle)
- §2 Global Specifications — 2.1 User and Role-Based Access Control; 2.2 API Response Structure (verbatim fixed block); 2.3 Pagination; 2.4 Common Resource Properties; 2.5 The Logical Clock; 2.6 Optimistic Concurrency Control; 2.7 Precision, Rounding, and Monetary Values; 2.8 Nested Resource Retrieval and Reference Integrity; 2.9 Validation Precedence; 2.10 Hierarchical Consistency and Cascading Side Effects
- §3 Business Logic & Workflows — 3.1 Customers, Quick-Turn Lanes, and Order Intake; 3.2 Stackups, Impedance Specification Lines, and the DFM Gate; 3.3 Panelization, Array Yield, and Provisional Pricing; 3.4 Drill Programs and the CAM Review Loop; 3.5 Laminate Lots, Reservations, and Date-Code Control; 3.6 Release to the Floor, Lane Commitments, and Production Holds; 3.7 Impedance Coupons, the Microsection Lab, and Quality Disposition; 3.8 Electrical Test and the Defect Pareto; 3.9 Invoicing, Final Pricing, Cancellation, and Shipment
- §4 Endpoint Definitions (4-column table, all 73 endpoints)
- §5 Error Code Catalogue (2-column table, all 36 error IDs)

**Zero-Silence / Rule-Coverage categories covered (all eight):**
1. **Validation priority orderings** — §2.9 global precedence chain plus per-endpoint ordered guard chains in §3 (intake, release's 7-step chain, drill approve SoD→hole→aspect, reservation create, lock, array release, measurement, invoice, ship, complete-fab, qualify, retest, booking)
2. **OCC concurrency rules** — both rules expressed with write-endpoint framing, `expected_fab_order_version` / `expected_laminate_lot_version`, parent-version mismatch, `ERR_STALE_VERSION` + HTTP 412; explicit note that no other endpoint takes a version field
3. **Cross-entity side effects** — depth-3 cancel cascade (array→reservation→lot plus drill/coupon/booking/etest/lane arms), start-production consumption cascade, lot-expiry cascade, final-coupon-fail cascade (auto DefectRecord + `boards_scrapped`), supersede cascades, all with per-resource version bumps
4. **applies_to scopes** — multi-endpoint rules enumerate every endpoint (e.g., `ERR_INSUFFICIENT_LAMINATE` on reservation create, release, and unhold; `ERR_LANE_INACTIVE` on create and release; `ERR_DISPOSITION_FAILED` on ship and complete-fab)
5. **Field-level structured content** — all defaults, initial values, computed-field derivations (`panels_available` conservation, `expiry_date` = manufacture + 365 days, `laminate_lot_codes` sorted-asc traceability, yield/floor/ceil fields), and the `common_fields: false` carve-out for CouponMeasurement and DefectRecord (only `id` + `created_at`)
6. **Sibling-branch symmetry** — unhold dual branches, etest PASS/FAIL, measurement PASS/FAIL, lot expiry from RECEIVED vs QUALIFIED, PROVISIONAL vs FINAL pricing variants, SINGLE vs STATISTICAL disposition variants
7. **Tail** — all 11 state machines' transitions with preconditions paired to error IDs; all 8 calculations in precise reconstruction-safe prose (no pseudocode, no fuzzy words — mechanically verified); all 36 validation conditions matchable to error IDs in §2/§3 narrative

**Hard-contract reports:**
- Field coverage: 107 required identifiers (entity fields + endpoint inputs/query params), 107 present, 0 missing — PASS (after repairing `stackup_id` and `status`)
- Rule coverage: all categories expressed — PASS
- §3 path purity: 571 backtick tokens scanned, 0 path tokens, 0 bare-method tokens, 0 method+path combos — PASS

The withheld files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) and all sibling tasks were not accessed.

## Step 6: Generate Implementation — 2026-08-14T07:17:00.000Z

73 endpoints in the scaffold, 73 implemented. Everything matches.

Here is the summary:

---

## Implementation Summary

### File list under `implementation/`

| File | Purpose |
|------|---------|
| `start.sh` | Launcher: guards `pip install` behind flask import check, `exec python3 app.py` |
| `requirements.txt` | `flask>=3.0.0` |
| `app.py` | Entry point, all 73 route handlers, error handlers, pagination |
| `db.py` | In-memory `Store` class (16 entity dicts + logical clock + order number seq) |
| `errors.py` | `ApiError` exception class + all 36 error ID constants |
| `response.py` | Envelope helpers (`meta`/`response_type`/`data`) matching scaffold spec |
| `middleware.py` | Auth header extraction (`X-User-ID`/`X-User-Role`), role checking, customer ownership |
| `services.py` | Business logic: pricing, yield, state machines, cascades, serialization |

### Endpoint count: 73 implemented (matches scaffold §1.5 exactly)

### State machines implemented (11 total)
1. **FabOrder fab_status** — QUOTED → DFM_REVIEW → AWAITING_LAMINATE → RELEASED → IN_PRODUCTION → ON_HOLD ↔ IN_PRODUCTION/AWAITING_LAMINATE → AWAITING_ETEST → COMPLETED → SHIPPED, plus CANCELLED from 5 states with depth-3 cascade
2. **FabOrder quality_disposition** — PENDING → PASSED (via complete-fab), PENDING → FAILED (final coupon fail), FAILED → CONDITIONAL (concede), CONDITIONAL → PASSED (requalify)
3. **Stackup** — DRAFT → LOCKED → SUPERSEDED
4. **PanelArray** — DRAFT → RELEASED → SUPERSEDED/CANCELLED
5. **DrillProgram** — DRAFT → UNDER_REVIEW → APPROVED/REJECTED → DRAFT (revise loop) → CANCELLED
6. **LaminateLot** — RECEIVED → QUALIFIED → DEPLETED ↔ QUALIFIED, RECEIVED/QUALIFIED → EXPIRED (with cascade), RECEIVED/QUALIFIED → QUARANTINED
7. **LaminateReservation** — RESERVED → CONSUMED/RELEASED
8. **ImpedanceCoupon** — AWAITING_MEASURE → PASSED/FAILED → AWAITING_MEASURE (retest, max 2) → CANCELLED
9. **LabSlotBooking** — BOOKED → COMPLETED/CANCELLED
10. **ElecTestRun** — SCHEDULED → RUNNING → COMPLETED_PASS/COMPLETED_FAIL/CANCELLED
11. **Invoice** — DRAFT → ISSUED → PAID

### Calculations implemented (8 total)
1. **panel_array_yield** — board/panel area, yield floor at 0.50 (4dp), good boards floor, panels ceiling, utilization (2dp round-half-up)
2. **order_pricing** — PROVISIONAL (panels_required basis, retest=0) and FINAL (actual_panels_run basis, retest fees) variants; pinned rounding: per-line round-half-up → sum → multiply → round → max(2000)
3. **impedance_disposition** — SINGLE (single reading in band) and STATISTICAL (both legs in band + spread ≤ 6.0) variants
4. **aspect_ratio_check** — thickness/min_hole at full float precision, ceiling 8.0 (1oz) / 6.0 (2oz), inclusive
5. **laminate_date_code_window** — expiry = manufacture + 365 days, usable while clock < expiry, reservation requires expiry > ship_date (strict)
6. **lane_capacity_commitment** — committed boards per lane+UTC-midnight date, equality allowed
7. **defect_pareto** — MAJOR/SCRAP filter, boards DESC + code ASC, pct/cumulative from unrounded fractions (2dp), vital-few at 80% threshold
8. **credit_authorization_check** — provisional_total ≤ credit_limit (equality passes)

### start.sh confirmation
- Reads `$PORT` env var (default 10000): yes, via `os.environ.get("PORT", "10000")` in `app.py`
- Binds `0.0.0.0`: yes, `app.run(host="0.0.0.0", ...)`
- Runs in foreground: yes, `exec python3 app.py` in `start.sh`
- Dependency install guarded: yes, `if ! python3 -c "import flask"` guard prevents re-install on every per-test reboot
- No state persistence: in-memory dicts only, no files, no seeding — verified state wipe across restarts

## Step 5: Generate Unit Tests — 2026-08-14T07:40:00.000Z

Generation complete and fully audited. Summary:

## Counts
- **Queue A (Difficulty): 36 tests** — 18 of 20 instances × ≥2 tests each. 2 instances skipped.
- **Queue B (Corner): 55 tests** — 55 of 58 non-stub instances × 1 test each. 3 instances skipped. All 22 `excluded_because:` stubs correctly not translated (cross-references verified to resolve to real queue-A instances).
- **Total: 91 tests**, all collecting cleanly under `pytest --collect-only`.

## Skip list (PRD-first filter: exact cent totals not uniquely derivable — PRD §3.3 narrates the pricing formula and pins the 2,500c impedance fee / 2,000c floor, but never publishes the numeric per-layer-count or per-finish rates)
- **A** `dual_variant_calc/provisional_vs_final_pricing_diverge` — asserts 68248 vs 73615; both require unpublished rates.
- **A** `combinatorial_formula/per_line_rounding_order_pinned` — asserts 2343 vs 2344; rounding order is in PRD but concrete line values are not derivable.
- **B** `calculations/min_lot_charge_floor_applied` — asserts total == 2000 via subtotal 1856; subtotal needs the rates.
- **B** `calculations/credit_limit_exact_boundary` — needs price == 68248 pre-known to construct the equality boundary; `credit_limit_cents` is create-only.
- **B** `calculations/quick_turn_premium_multiplier_applied` — asserts 102372 == 68248×1.50; rate-dependent.

Relaxed-but-emitted (derivable core kept, rate-dependent literals dropped): `order_read_includes_computed_fields` (keeps `laminate_lot_codes == []` + non-null int price), `derived_price_recomputed_on_stackup_lock` (relational: lock adds exactly +2500 — the fee IS in PRD), `invoice_lifecycle_draft_to_paid` (lifecycle only), `create_customer_applies_defaults` and `system_fields_input_ignored` (PRD pins neither `version`'s initial value nor the created_at string form). Pareto row inner key names are not PRD-pinned, so the Pareto test uses a tolerant key resolver while keeping all numbers/ordering exact.

## Files
- **test_helpers/** (9): `__init__.py` (barrel), `types.py` (16 entity TypedDicts + 17 enums; append-only `CouponMeasurement`/`DefectRecord` omit `updated_at`/`version`), `api_client.py` (77 endpoint methods), `api_errors.py` (36 error IDs + HTTP map registered with the framework), `assertions.py` (per-entity + lot-conservation + Pareto row accessor), `factories.py`, `constants.py` (G1 geometry, thresholds, clock-safe booking windows), `test_users.py` (shared opaque-role headers + `make_customer_headers` entity-backed builder), `fixtures.py` (5 tiers: granular creators → `prepare_order` pipeline → `setup_released/in_production/awaiting_etest/completed/shipped` → `drive_coupon_to_final_fail`, OCC version threading built in).
- **test_suite/** (13): `conftest.py` + `test_01_customers_and_order_intake.py`, `test_02_stackups_dfm_and_drill.py`, `test_03_aspect_ratio_boundaries.py`, `test_04_panelization_yield_and_pricing.py`, `test_05_laminate_lots_and_reservations.py`, `test_06_clock_expiry_cascade.py`, `test_07_release_and_lane_capacity.py`, `test_08_production_holds_and_traceability.py`, `test_09_coupons_lab_and_measurements.py`, `test_10_etest_defects_pareto.py`, `test_11_cancellation_cascades.py`, `test_12_invoices_and_shipment.py`.

## Tag confirmation
Programmatic audit confirms: every one of the 91 tests carries **exactly one** `Design:` tag, as the docstring's last line, resolving to a real non-stub instance; queue-A coverage ≥2/instance and queue-B ≥1/instance hold for every emitted tag; every docstring's quoted PRD citation survives a verbatim whitespace-normalized grep of `workspace/PRD.md`; no `skip`/`xfail` markers and no scaffold references exist anywhere in the generated code.

## Step 7: Run Tests and Iterate — 2026-08-14T08:05:00.000Z

## Summary

**Iterations run:** 5 sweeps total (1 baseline + 3 fix-validation + 1 final confirmation after a harness-side kill ate the results files of sweep 4). Final state: **all 8 parallel rounds at 91/91 passed**.

**Baseline failures (6 tests, deterministic 8/8 rounds):** `test_expired_lot_qualify_rejected`, `test_clock_set_past_expiry_cascades`, `test_final_fail_on_non_required_line_blocks_complete_fab`, `test_booking_duration_limit`, `test_pareto_ordering_tiebreak_and_vital_few`, `test_pareto_empty_window`.

**Tests deleted:** none. Every failure traced to either a genuine implementation bug or a fixable test/fixture defect; no PRD-silence or unique-derivability deletions were needed.

**Fixes applied to `test_helpers/`:**
- `/home/ubuntu/github/CodingPRD/tasks/task_1662_printed_circuit_board_fabrication/test_helpers/assertions.py` — added `assert_same_instant(actual, expected)`: PRD pins the *instant* (§2.5 "responds with the resulting current_utc", §3.8 "reports the window_start, the window_end") but never the serialized string form, so equality is judged on parsed instants (STEP 1c partial-coverage correction).
- `/home/ubuntu/github/CodingPRD/tasks/task_1662_printed_circuit_board_fabrication/test_helpers/constants.py` — `CLOCK_0300` changed `03:00:00Z` → `03:15:00Z`: the paired `WINDOW_AT_0300` opens at 03:15 (15-minute station clearance from the 02:00–03:00 booking), and PRD §3.7 admits a measurement only when the clock falls at-or-after `starts_at`; the fixture's clock sat outside its own window, so the implementation correctly rejected the setup.

**Fixes applied to `test_suite/`:**
- `test_06_clock_expiry_cascade.py` — `current_utc` assertion switched from raw-string equality to `assert_same_instant`.
- `test_10_etest_defects_pareto.py` — `window_start`/`window_end` assertions in both Pareto tests switched to `assert_same_instant`.
- `test_09_coupons_lab_and_measurements.py` (`test_booking_duration_limit`) — the "121 minutes" payload was actually 61 minutes (`13:00→14:01`); corrected `ends_at` to `15:01` so the payload genuinely exceeds the PRD §3.7 120-minute cap.

**Fixes applied to `implementation/`:**
- `/home/ubuntu/github/CodingPRD/tasks/task_1662_printed_circuit_board_fabrication/workspace/implementation/app.py` — `qualify_lot` now fetches the lot directly from the store (bypassing `svc.get_lot`, which lazily expires) and evaluates the guard chain on stored status: state guard first, then `clock >= expiry_date` → `ERR_LOT_NOT_QUALIFIED`. PRD §3.5 verbatim: "Qualification is refused when the clock has reached the lot's `expiry_date` … surfacing `ERR_LOT_NOT_QUALIFIED`; the state guard (lot not in `RECEIVED`) takes precedence when both apply" — the lazy flip inside the handler made the named error unreachable.
- `/home/ubuntu/github/CodingPRD/tasks/task_1662_printed_circuit_board_fabrication/workspace/implementation/services.py` — `serialize_laminate_lot(lot, recompute=True)` gained a flag; `create_laminate_lot` now passes `recompute=False`, because PRD §3.5 states "The lot opens in `RECEIVED` status" — the create endpoint was eagerly flipping an at-expiry lot to `EXPIRED` at creation, which poisoned the later qualify guard. Lazy expiry re-evaluation still fires on every subsequent access (GET/list), so `test_received_lot_expires_lazily_on_access` and the clock-set cascade behavior are unchanged.

**Note:** sweeps 2–4's interleaved stdout glued one round's test-name chunk to another round's FAILED marker (classic `pytest -v` split-write artifact); the per-round `results.*.json` files were used as the sole source of truth, as the protocol requires.

Orchestrator verification: all 8 `results.{1..8}.json` show passed=91 total=91.

## Step 8: Finalize PRD — 2026-08-14T08:20:00.000Z

The diff is exactly the three in-place sentence-level revisions (no lines added/removed — line count identical at 324, 0.00% delta; edits are inline revisions within existing paragraphs, consistent with "no new sections, change as little as possible").

## Summary

**Line counts:** PRD.md = 324 lines, PRD_FINALIZED.md = 324 lines, delta 0 lines (0.00%). Three paragraphs were revised inline; no sections added or removed.

**Changes (one bullet each):**

- **§2.4 (Common Resource Properties)** — revise — appended a sentence pinning that every timestamp the API emits (entity fields and ad-hoc response fields, explicitly naming the clock's `current_utc` and the Pareto report's `window_start`/`window_end`) is serialized as ISO 8601 UTC with three fractional digits, e.g. `2026-08-01T00:00:00.000Z` — `implementation/services.py:61-67` (`iso_str`), `services.py:42-45` (`now_iso`), `app.py:142` (`current_utc`), `app.py:1880-1881` (`window_start`/`window_end`).

- **§3.5 (qualification paragraph)** — revise — appended a sentence pinning that the qualify action evaluates its guard chain against the lot's *stored* status without first performing lazy expiry re-evaluation: stored-`RECEIVED` + clock at/past `expiry_date` → `ERR_LOT_NOT_QUALIFIED` (no pre-guard flip to `EXPIRED`); only a lot stored in another status draws `ERR_INVALID_STATE` — `implementation/app.py:1152-1177` (`qualify_lot` fetches the lot directly from the store, bypassing `svc.get_lot`'s lazy recompute).

- **§3.5 (expiry paragraph)** — revise — inserted two sentences pinning the two exemptions from lazy expiry re-evaluation: (1) lot receipt — a newly created lot opens and is reported in `RECEIVED` even when the clock already stands at/past its computed `expiry_date`, with the first subsequent access flipping it to `EXPIRED`; (2) the qualification guard chain — `implementation/app.py:1115` (`serialize_laminate_lot(lot, recompute=False)` in `create_laminate_lot`), `implementation/services.py:138-160` (`serialize_laminate_lot` recompute flag).

**Step 7 items with no PRD edit (and why):**

- `test_helpers/constants.py` `CLOCK_0300` 03:00→03:15 — pure fixture bug; PRD §3.7 already pins "the clock must fall at or after `starts_at` and strictly before `ends_at`".
- `test_09` `test_booking_duration_limit` payload fix (61→121 min) — pure test bug; PRD §3.7 already pins the 120-minute cap verbatim.
- The `assert_same_instant` test-side switches in test_06/test_10 — these are the *evidence* of the serialization silence; the pin itself is the §2.4 edit above.

**Per-edit pre-edit search log:**

1. **§2.4 serialization edit.**
   - (a) Subject: serialized string form of every emitted timestamp, in particular `current_utc` (§2.5) and `window_start`/`window_end` (§3.8).
   - (b) Paths enumerated/read: `app.py:129-142` (`set_clock` → `svc.iso_str`), `app.py:1825-1883` (`defect_pareto` → `svc.iso_str` for both window fields), `app.py:1474` (`measured_at` → `now_iso`), all `serialize_*` functions in `services.py:111-374` (every datetime field via `iso_str`), `services.py:42-67` (both formatters emit `%Y-%m-%dT%H:%M:%S.mmmZ`), `response.py:18` (envelope `api_request_timestamp`, same format), and intake parses at `app.py:333, 1093, 1552-1553, 1770` confirming client strings are never echoed raw.
   - (c) Wording adjustment: instead of pinning `current_utc`/`window_start`/`window_end` field-by-field (which would risk implying other fields are unpinned), I used one universal sentence covering all emitted timestamps — verified consistent with every enumerated path.

2. **§3.5 qualification paragraph edit.**
   - (a) Subject: whether lazy expiry re-evaluation fires inside the qualify action, and against what status the qualify guard chain runs.
   - (b) Paths enumerated/read: all 13 `recompute_lot_status`/`serialize_laminate_lot`/`get_lot` call sites — `app.py:141` (clock set), `479` (release-order guard recomputes reservation lots), `1115` (create, `recompute=False`), `1124-1125` (GET, lazy), `1140` (list, lazy), `1152-1177` (qualify, **no** recompute), `1183-1184` (quarantine, lazy), `1232` (reservation create, recompute before QUALIFIED guard), `1268` (post-reserve depletion recompute); plus `services.py:400-405` (`get_lot` recomputes), `470-494` (`recompute_lot_status`), `497-501` (expiry cascade only from `QUALIFIED`).
   - (c) Wording adjustment: I deliberately did **not** narrow the existing "re-evaluated … on every access" clause to "reads only", because quarantine, reservation create, and the release guard also recompute — "reads only" would have been a new mismatch. The inserted sentence carves out exactly the one exempt action (qualify) and describes the two guard outcomes precisely as implemented.

3. **§3.5 expiry paragraph edit.**
   - (a) Subject: whether lot creation eagerly flips an at-expiry lot to `EXPIRED`.
   - (b) Paths enumerated/read: same enumeration as edit 2, with focus on `app.py:1080-1115` (`create_laminate_lot`: stores `status: "RECEIVED"`, serializes with `recompute=False`) and `services.py:138-144` (the `recompute` flag and its comment); confirmed the flip still fires on the next lazy access (`get_lot`, list, quarantine, reserve, release guard, clock set) so existing cascade behavior (`test_received_lot_expires_lazily_on_access`, clock-set cascade) is preserved.
   - (c) Wording adjustment: scoped the exemption to exactly "two moments" (receipt and the qualification guard chain) and explicitly stated the first subsequent access re-evaluates — avoiding any claim that expiry is never re-evaluated for a young lot, which would contradict `app.py:1124/1140/1184/1232`.

No new mismatch introduced: both §3.5 carve-outs enumerate exactly the exempt paths and leave the general lazy-re-evaluation rule intact for all other call sites, and the §2.4 universal serialization claim was verified against every timestamp emitter in the implementation.

PRD_FINALIZED.md is at `/home/ubuntu/github/CodingPRD/tasks/task_1662_printed_circuit_board_fabrication/workspace/PRD_FINALIZED.md`.

## Step 9: Complete PRD — 2026-08-14T08:40:00.000Z

All edits are applied and verified. Final report:

## Summary

**Source vs. output**: `/home/ubuntu/github/CodingPRD/tasks/task_1662_printed_circuit_board_fabrication/workspace/PRD_FINALIZED.md` (324 lines, 57,190 chars) → `/home/ubuntu/github/CodingPRD/tasks/task_1662_printed_circuit_board_fabrication/workspace/PRD_COMPLETED.md` (324 lines, 60,357 chars; **+3,167 chars**, line count unchanged — all changes are in-paragraph inserts/revisions, no new sections).

**Counts**: 12 ambiguity-pins, 7 mismatch-revisions (19 paragraphs touched).

### Ambiguity-pins (PRD silent → inserted impl behavior)

- §2.3 — insert — ambiguity — out-of-range `limit`/`offset` are clamped into range; non-numeric values fall back to defaults rather than failing — `implementation/app.py:44-55`
- §2.4 — insert — ambiguity — `version` starts at exactly 1 on creation — `implementation/services.py:80-87`
- §2.4 — insert — ambiguity — entity timestamps are stamped from the logical clock; only the envelope's `api_request_timestamp` is wall-clock — `implementation/services.py:42-45`, `implementation/response.py:14-18`
- §2.6 — insert — ambiguity — both OCC checks are exact-equality: a supplied version ahead of current is also `ERR_STALE_VERSION` — `implementation/app.py:843-845`, `implementation/app.py:1250-1253`
- §3.1 — insert — ambiguity — duplicate `lane_code` is rejected with `ERR_VALIDATION` (no dedicated error exists, unlike email/lot_code) — `implementation/app.py:215-217`
- §3.3 — insert — ambiguity — `panels_required` is zero when `good_boards_per_panel` is zero (division undefined) — `implementation/services.py:643-645`
- §3.3 — insert — ambiguity — pins the pricing rate tables the PRD never gave: layer rates 120/200/300/420 cents per panel-sqin for 2/4/6/8 layers; finish rates HASL 40, OSP 35, ENIG 90, IMMERSION_SILVER 70, HARD_GOLD 160 — `implementation/services.py:28-35`
- §3.4 — insert — ambiguity — the `UNDER_REVIEW` transition guard precedes the three approval gates; a missing `LOCKED` stackup at approval is rejected with `ERR_ASPECT_RATIO_EXCEEDED`; the computed ratio is recorded on `plated_aspect_ratio` even when the gate rejects — `implementation/app.py:1011-1034`
- §3.6 — insert — ambiguity — unhold with no `RELEASED` array returns to `AWAITING_LAMINATE` unconditionally (no coverage check) — `implementation/app.py:556-562`
- §3.7 — insert — ambiguity — coupon create evaluates the order-state guard before the `spec_line_id` reference check, and the spec line is not required to belong to the order's own stackup — `implementation/app.py:1321-1335`
- §3.7 — insert — ambiguity — final coupon failure with no `RELEASED` array auto-creates the defect with null `panel_array_id` and zero `boards_affected`, leaving `boards_scrapped` unchanged — `implementation/app.py:1495-1512`
- §3.8 — insert — ambiguity — an e-test run may be completed only from `RUNNING` — `implementation/app.py:1699-1700`
- §3.8 — insert — ambiguity — pins Pareto row JSON keys (`defect_code`, `boards`, `pct`, `cumulative_pct`, `vital_few`) and that the vital-few test compares the unrounded cumulative share against 80 — `implementation/app.py:1863-1877`
- §3.9 — insert — ambiguity — invoice `line_items` is an array of `{line_type, amount_cents}` in base/finish/impedance/retest order; invoice creation requires a `RELEASED` array (else `ERR_INVALID_STATE`) — `implementation/app.py:1914-1916`, `implementation/services.py:615-620`
- §3.9 — insert — ambiguity — "coupon not in a terminal state" pinned as not in `PASSED`/`CANCELLED` (FAILED coupons are cancelled with the order) — `implementation/services.py:735-740`

(That is 15 insert-type items; reclassifying precisely: 12 pure inserts + 3 of the items above — §2.4 version, §3.8 vital-few rounding, §3.9 coupon-terminal — revised existing wording to resolve ambiguity. Total ambiguity-pins: 15. Recount of mismatches below is 4+3=7 as stated; totals: 15 pins + 7 revisions = 22 change-points across 19 paragraphs.)

### Mismatch-revisions (PRD described different behavior → revised to impl)

- §2.9 — revise — mismatch — `ERR_SOD_VIOLATION` no longer ranked ahead of state guards; impl evaluates the `UNDER_REVIEW` transition guard first, SoD immediately after — `implementation/app.py:1011-1016`
- §2.9 — revise — mismatch — field-shape validation is not "evaluated last": required-field presence is checked when the body is first read (post auth/path-existence, pre reference/state/domain), and each field's shape is validated at first consultation — `implementation/app.py:66-122` and every handler's `require_fields` placement
- §3.1 — revise — mismatch — `tax_exempt` is carried on the customer record only (invoices never expose it), not "for invoice display" — `implementation/services.py:111-121`, `implementation/services.py:362-374`
- §3.1 — revise — mismatch — intake precedence is customer-ref → ownership → lane-ref (not all references before ownership), and shape errors surface at first field consultation (e.g. invalid `service_lane` precedes the customer reference check) — `implementation/app.py:289-345`
- §3.6 — revise — mismatch — shipped orders continue to occupy lane capacity (impl never decrements the commitment at ship); committed-boards state list now includes `SHIPPED` — `implementation/app.py:600-617` (no decrement), `implementation/services.py:754-758`
- §3.9 — revise — mismatch — lane-commitment reduction on cancel is keyed to cancellation from `RELEASED`/`ON_HOLD` (the only reachable commitment-era states), upserting the row even to a negative balance — `implementation/services.py:754-758`
- §3.7 — revise — mismatch — measurement guard order is state → required-field presence (`ERR_VALIDATION`) → booking guard → remaining shape checks, not state → booking → shape — `implementation/app.py:1416-1447`

Everything else in the implementation (all 60 endpoint role lists, state machines, guard chains in §3.5/§3.6/§3.9, yield and pricing rounding order, expiry cascade semantics including the qualify-time exemption, cancel cascade links, retest budget, and the response envelopes) was verified to already be uniquely pinned by the PRD and was left untouched.
