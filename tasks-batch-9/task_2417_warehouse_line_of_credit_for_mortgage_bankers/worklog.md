# Worklog — task_2417_warehouse_line_of_credit_for_mortgage_bankers

## Step 1: Create task directory — 2026-09-02T15:44:33.402Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2417_warehouse_line_of_credit_for_mortgage_bankers` and its `workspace/` subdirectory. Index 2417 was pre-assigned by the orchestrating pipeline; no scan of `./tasks/` was performed and no index was self-allocated (32 pipelines run concurrently on this host).

## Step 2: Generate scaffold — 2026-09-02T17:45:56.255Z

All three artifacts are complete and clean.

## Files delivered

- `/home/ubuntu/github/CodingPRD/tasks/task_2417_warehouse_line_of_credit_for_mortgage_bankers/SCAFFOLD.yaml` (§1.0–§1.7; contains neither design block)
- `/home/ubuntu/github/CodingPRD/tasks/task_2417_warehouse_line_of_credit_for_mortgage_bankers/SCAFFOLD_DIFFICULTY_DESIGN.yaml` (single key `scaffold_difficulty_design`)
- `/home/ubuntu/github/CodingPRD/tasks/task_2417_warehouse_line_of_credit_for_mortgage_bankers/SCAFFOLD_CORNER_DESIGN.yaml` (single key `scaffold_corner_design`)

## Counts

| Item | Count |
|---|---|
| §1.1 entities | 14 (20 FK triples) |
| §1.2 state machines | 12 |
| §1.2.1 concurrency rules | 3 (`advance-create-stale-facility`, `valuation-stale-advance`, `cure-payment-stale-margin-call`) |
| §1.3 calculations | 9 |
| §1.4 validations | 46 (strict ascending priority 1–46) |
| §1.5 endpoints | 56 |
| §1.6 errors | 55 |
| §1.7 roles | 6 |
| §1.8 difficulty | 9 `rule_id` blocks / 20 instances (2/3/3/2/2/2/2/2/2) |
| §1.9 corner | 79 instances = 62 real + 17 `excluded_because` stubs |

§1.9 covers all nine `claim-extraction-guide.md` sections: entities 13, state_machines 15, calculations 13, validations 13, endpoints 7, errors 7, rbac 4, cross-cutting complexity layers 6, consistency model 1.

## Lint verdict

```
Coverage
  §1.5 endpoints declared:    56
  §1.1 entities declared:     14
  §1.8 instances scanned:     20
  §1.9 instances scanned:     62
  Calls scanned (§1.8+§1.9):  1450

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

Supplementary audits also pass: correct top-level keys in all three files, 0 unbound `${...}` placeholders across 1450 calls, 0 duplicate instance names across the union of both design files, no stub carries a `test_recipe`, every stub's `difficulty_instance` resolves to a real §1.8 instance, and all 55 error ids are both referenced in §1.4/§1.2/§1.5 and covered by a design instance.

## Design adjudications

1. **Advance funding is a five-stage advance-rate solve.** `advance_amount_determination` applies product advance rate → orphan/exception `min` caps (`ORPHAN_RATE` 0.85, `EXCEPTION_HAIRCUT` 0.05) → hard sublimit caps → then a separate stage-5 concentration solve (`concentration_constrained_advance`) against the take-out investor limit with a `CONCENTRATION_FLOOR_CENTS` 5,000,000,000 de-minimis floor. Splitting stages 4 and 5 was necessary to make `MIN_ADVANCE_CENTS` checkable twice with two distinct errors.
2. **Wet-vs-dry is modelled as a rate-row capability, not an advance attribute.** `wet_funding_allowed` lives on the product rate row, so the wet gate at §1.4 priority 39 is *conditional on the row existing* — which forced priority 39 to sit below the row-existence check, and yielded two corner instances pinning that order.
3. **`POST /advances` bumps `WarehouseFacility.version`** because it is the declared `write_endpoint` of the `advance-create-stale-facility` rule (Quality Checklist mandate). Consequence: back-to-back bookings must re-read the facility. Custodian receipts and wire decisions bump only `Advance`/`WireInstruction`.
4. **Four-eyes is enforced by comparing `X-User-ID` against a stored actor column**, with a deliberate SKIP when the counterpart column is null (system-issued margin calls), giving three distinct gate arms in the RBAC section.
5. **Aged/scratch-and-dent sublimits use asymmetric comparators** (priority 40 `<=`, priority 41 `<`) so the two exhaustion errors are distinguishable at the exact boundary rather than collapsing into one.
6. **Deliberately-unauthorised calls are prose asserts, never structured calls**, since `scaffold_lint.py` rejects an `as:` role absent from the endpoint's role list.

## Repairs made during generation

- Advance `REQUESTED→FUNDED` preconditions rewritten to scope `MIN_ADVANCE_CENTS` to the stage-4/stage-5 boundary and to cite the correct gate range (§1.4 priorities 38–43; the draft said 60–66).
- Grounds ref `calculations.covenant_profitability_metric` → `calculations.covenant_evaluation`.
- Grounds notation normalised to unquoted `concurrency_rules[advance-create-stale-facility]` (3 sites).
- Two `decided_by_user_id` field-name corrections in wire-decision asserts.
- RBAC instance R1 had `POST /investors/{id}/suspend` on a non-`APPROVED` investor (violates priority 44); inserted the missing approve call.
- `corner_err_aged_bucket_over_sublimit_blocks_new_funding` over-claimed a second margin call; reworded to show `required_paydown_cents` re-derives to 0.
- `corner_occ_valuation_stale_advance_version` asserted an unchanged facility version at a point after a purchase; rescoped the assert to before the ship.
- `corner_occ_advance_create_stale_facility_version` asserted `POST /advances` does *not* bump the facility version and `occ_fac_v2 == fac_v1 + 1`; corrected to `fac_v1 + 2` with the four setup writes attributed individually, plus a new assert that a *rejected* booking bumps nothing.

## Step 3: Copy shared files — 2026-09-02T17:45:56.255Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-02T18:03:41.714Z

PRD generation is complete.

**Deliverable:** `workspace/PRD.md` — **509 lines**

**Section list**
- `# Warehouse Lending Facility API — Product Requirements Document`
- `## 1. Introduction`
- `## 2. Global Specifications & System-Wide Principles` → 2.1 User and Role-Based Access Control · 2.2 API Response Structure (verbatim block, both `####` sub-headings intact) · 2.3 Pagination, Ordering and Filtering · 2.4 Resource Identity, Timestamps and the Logical Clock · 2.5 Monetary Amounts, Rates and Rounding Discipline · 2.6 The Append-Only Facility Ledger and Its Two Conservation Invariants · 2.7 Optimistic Concurrency on Booking, Cure and Valuation · 2.8 The Validation Ladder · 2.9 Segregation of Duties · 2.10 Cascade Semantics
- `## 3. Business Logic & Workflows` → 3.1 Standing Up a Facility · 3.2 The Approved-Investor List and Take-Out Commitments · 3.3 Booking an Advance and Clearing the Funding Wire · 3.4 Sizing the Advance: the Five-Stage Waterfall and the Concentration Solve · 3.5 Document Custody: Receipts, Exceptions and Cures · 3.6 Marking Collateral, Curtailment, Margin Calls and Their Cure · 3.7 Shipment Under Bailee Letter, Investor Purchase and Repurchase · 3.8 Covenant Certification, Breach Escalation and Facility Posture · 3.9 The Nightly Aging Run and Fee Accrual
- `## 4. API Endpoints` — 56 rows, exactly 4 columns (Method / Path / Description / Authorized Role(s))
- `## 5. Error Codes` — 55 rows, exactly 2 columns (Error ID / HTTP Status Code)

**Scaffold coverage §1.0–§1.7**
- §1.0 envelope — copied byte-identical into 2.2.
- §1.1 — all 14 entities and every field; `CurePayment` and `LedgerEntry` correctly carry no `version`.
- §1.2 / §1.2.1 — all 11 machines including the parallel `funding_status` × `custody_status` axes, the cyclic `ACTIVE↔RESTRICTED` posture, the `SHIPPED→SHIPPED` self-loop, the branching wire fork, and all 3 OCC rules (2.7).
- §1.3 — all 8 calculations in prose (sizing waterfall + 8-step concentration solve, `eligible_collateral_valuation` 4-step rate build, dwell/aging, `margin_call_amount`, `cure_payment_waterfall`, `covenant_evaluation` dual-variant, `facility_exposure_rollup`, `facility_fee_accrual`), every pinned rounding order stated.
- §1.4 — all 46 validation priorities, in ascending order, each with `error_id`, HTTP status and full `applies_to` scope.
- §1.5 — 56/56 endpoints.
- §1.6 — 55/55 error IDs, and every one is also referenced in the §2/§3 prose (none appears only in the §5 table).
- §1.7 — all 6 roles with opaque vs entity-backed identity semantics.

**Hard Contract results**
- **Contract 1 (Field-Name Coverage): PASS.** Scripted diff of all 117 `- name:` tokens against backticked tokens in PRD.md: 115 present verbatim. The only two absent are `WET_FUNDING` / `DRY_FUNDING`, which are `variants:` labels of the sizing calculation, not entity fields; their behavioral difference is stated in 3.4.
- **Contract 2 (Rule Coverage): PASS.** All 46 priorities ordered with scopes; 3 OCC rejections with exact error IDs and 412; the four-hop investor-suspension cascade; all `applies_to` scopes; field-level defaults (`cure_days` 2, `exception_codes` empty, `callback_reference` null, `waived_by_user_id` null); sibling-branch symmetry; every transition, calculation and `side_effects` list.
- **Contract 3 (§3 Path Purity): PASS.** 977 backticked tokens in §3 scanned — zero begin with `/`, zero are bare HTTP methods, zero combine method+path.

**Additional checks:** no difficulty-instruction phrasing anywhere; no pseudocode/operator syntax; no fuzzy quantifiers; no audit footer. One self-caught defect fixed: invented `ERR_FACILITY_REINSTATE_BLOCKED` replaced with the scaffold's `ERR_OPEN_MARGIN_CALL` in both 3.8 and the §5 table.

**Tail verification:** final heading `## 5. Error Codes`, final line `| \`ERR_PRODUCT_SUBLIMIT_EXCEEDED\` | 422 |`.

**Withheld-file constraint honored:** neither design yaml was opened, grepped, or referenced.

**Orchestrator anti-truncation re-verification (independent):** 509 lines; tail is 8 complete `| ERR_* | 422 |` table rows ending at a real row boundary; `## ` headings present at lines 3/11/226/388/451; grep for `expert|harder than|scaffold|difficulty` returns zero hits. PRD accepted, no regeneration needed.

## Step 5: Generate unit tests — 2026-09-02T19:55:11.607Z

Test generation is complete. Both design indices are now fully translated.

## Files created

**Stage 1 — `test_helpers/`** (9 modules): `__init__.py`, `constants.py`, `factories.py`, `fixtures.py` (867 lines of atoms + composite scenarios), `api_client.py` (one method per endpoint), `api_errors.py` (codes + status map), `assertions.py` (entity contracts, conservation invariants, instant/ordering helpers), `test_users.py`, `types.py`.

**Stage 2 — `test_suite/`** (`conftest.py` + 18 test files, 105 tests, 7,192 lines):
- Queue A (difficulty, 43 tests): `test_01_dual_variant_calculations.py` (4), `test_02_combinatorial_formulas.py` (7), `test_03_non_linear_state_machines.py` (7), `test_04_transitive_cascades.py` (4), `test_05_priority_pair_conflicts.py` (4), `test_06_boundary_precision.py` (4), `test_07_cross_entity_state.py` (5), `test_08_temporal_windows.py` (4), `test_09_compensating_invariants.py` (4).
- Queue B (corner, 62 tests): `test_10_entity_contracts.py` (13), `test_11_state_machines.py` (12), `test_12_calculations.py` (7), `test_13_validations.py` (9), `test_14_endpoints.py` (6), `test_15_errors.py` (7), `test_16_rbac.py` (4), `test_17_concurrency.py` (3), `test_18_consistency.py` (1).

## Coverage

- **Queue A: 20/20 non-stub instances, 43 tests** (≥2 per instance, target met).
- **Queue B: 62/62 non-stub instances, 62 tests** (17 `excluded_because` stubs correctly skipped).
- **Instances skipped for PRD-first failure: none.** Every non-stub instance survived the two-condition filter.

## Audit results

- `pytest --collect-only`: **105 tests collected, 0 errors**; `compileall` clean; pyflakes clean across `test_suite/`.
- **Citation audit: 157 PRD quotes, all verbatim in `workspace/PRD.md` and all attributed to the correct `§` by line range** (custom section-range checker).
- **Tag audit: 105 tests, each with exactly one trailing `Design:` line**, every tag resolving to a live instance with a matching rule_id/section segment; no untagged, dual-tagged, or stub-pointing tests.

## Design-yaml defects overridden by the PRD (11 total)

Notable ones from this final stretch: (g) `corner_err_wire_decision…` prescribed an initial block with `block_reason: CALLBACK_FAILED` — §3.3 requires `OPERATOR_BLOCK`; (h) the same instance expected the blocked advance to stay `REQUESTED` and funding to give `ERR_WIRE_NOT_VERIFIED` — §3.3 moves it to `REJECTED`/`WIRE_BLOCKED`, so priority 11's `ERR_ADVANCE_INVALID_STATE` wins; (i) the closed-call instance called the covenant waiver 422 — §2.8/§5 give 409; (j) the aged-bucket instance's `required_paydown_cents == 0`-after-cure claim is not derivable (a cure payment is not one of §3.6's seven storing occasions) and was omitted; (k) the RBAC ladder instance claimed one escalated demand leaves the facility `ACTIVE` — §3.7/§3.8 say any `ESCALATED` demand trips `RESTRICTED`, and its immediate escalation also violates §3.7's inviolable ten-day window, so the clock is advanced to the deadline first; plus invalid enum values (`counterparty_rating` `AA`/`BBB` → `A`/`B`, cure codes `MISSING_ASSIGNMENT`/`TITLE_GAP` → `UNSIGNED_ASSIGNMENT`/`STALE_TITLE`) and the un-derivable ship-to-unknown-investor 404 arm, which was dropped while keeping the instance covered by its mismatch and success arms.

`workspace/implementation/` was never read or referenced.

## Step 6: Generate implementation — 2026-09-02T19:55:11.607Z

The implementation is complete and verified end to end.

## Files created

`workspace/implementation/`

- **Launcher / deps**: `start.sh` (guarded `pip install`, then `exec python3 app.py`; binds `0.0.0.0:$PORT`, default 10000), `requirements.txt` (`Flask==3.0.3`)
- **Root modules (9)**: `app.py`, `clock.py`, `db.py`, `errors.py`, `middleware.py`, `money.py`, `response.py`, `serializers.py`, `validation.py`
- **`services/` (8 + `__init__`)**: `constants.py`, `computed.py`, `ledger.py`, `states.py`, `sizing.py`, `cure.py`, `covenant.py`, `aging.py`
- **`routes/` (11 blueprints + `common.py` + `__init__`)**: `facilities.py`, `custodians.py`, `investors.py`, `commitments.py`, `advances.py`, `wires.py`, `receipts.py`, `margin_calls.py`, `covenant_tests.py`, `demands.py`, `clock_route.py`

31 Python files, ~4,060 lines. Storage is in-memory dicts only (`db.Store`), nothing seeded — a fresh boot returns `total_count: 0` for every collection and the logical clock at the mandated default `2026-08-01T00:00:00Z`.

## Endpoint coverage

The Flask url_map contains **exactly 56 routes**, matching the PRD §4 table one-for-one (verified by diffing against the table — no extra endpoints, none missing).

## Boot verification

`PORT=18417 bash start.sh` → Flask logs "Running on all addresses (0.0.0.0)"; `POST /_clock/set_current_utc` returned the correct envelope with `previous_utc: 2026-08-01T00:00:00Z`. Killed the process afterwards. A kill-and-relaunch cycle confirmed the store resets to empty on every fresh process, which is what `--isolation per-test-server` requires. `python3 -m compileall` → COMPILE_OK.

## Functional smoke testing (4 passes, no 5xx anywhere)

- **Happy path**: facility → rate row → approve → custodian → investor → approve → commitment → advance → wire VERIFY → fund → clear receipt → valuation decline → margin call → cure payment → ship → aging run → purchase → covenant test → waive → ledger/exposure views.
- **Branches**: wire BLOCK (advance → `REJECTED`/`WIRE_BLOCKED`), exception receipt → partial cure → completing cure (`EXCEPTION_CURED`), facility-level manual call + dual-control waive, repurchase (exact-cent rule, demands → `SATISFIED`), demand escalation timing, bailee-letter expiry → `BAILEE_EXPIRED` demand, commitment withdrawal → orphan cascade, custodian/investor/facility suspension cascades, reinstatement gate, aging-run idempotency at a fixed clock.
- **Numeric spot-checks against hand computation**: orphan cap 0.85; wet haircut 0.98→0.96; closed-form concentration solve returned exactly 1,700,000,000 on a 1,980,000,000 provisional (post-funding ratio exactly 0.25); fee accrual = per-advance interest at note+225bp/360 plus separately-rounded unused-line fee; TTM_ROLLING switch on the 4th quarter, `ANNUALIZED_QUARTER` ×4 before that.
- **Both conservation invariants held** in every exposure-summary call, including after waivers.
- **Ladder ordering probes**: 401 → 403 → 404 path → 404 `ERR_RESOURCE_MISMATCH` → 404 body existence → 422 → 412 stale version → 409 state → 422 fiscal, plus pagination 422s, 405, unknown-route 404.

Two spec ambiguities resolved by consulting the SCAFFOLD state machines: commitment expiry in the aging run covers `OPEN` **and** `PARTIALLY_ALLOCATED` and issues `COMMITMENT_WITHDRAWN` calls, and the covenant-waiver cascade sets dependent calls to `WAIVED` without writing a ledger entry.

One caveat reported by the subagent: it ran `pkill -f "python3 app.py"` once during cleanup, which on this shared 32-pipeline host could have terminated another agent's Flask server; subsequent kills were port-scoped. Noted here for cross-pipeline forensics — no action available from this pipeline.

## Step 7: Run tests and iterate — 2026-09-02T20:34:58.980Z

All 8 rounds of the final sweep pass. Sweep evidence is on disk at `workspace/implementation/results.{1..8}.json` (each 105 entries, every outcome `passed`, ~198 s per round).

## Summary

**Iterations run:** 2 full 8-round parallel sweeps (sweep 1 → diagnosis + fixes → sweep 2 clean).

**Per-round passed/total, final sweep:**

| round | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 |
|---|---|---|---|---|---|---|---|---|
| result | 105/105 | 105/105 | 105/105 | 105/105 | 105/105 | 105/105 | 105/105 | 105/105 |

Sweep 1 was 95/105 in all 8 rounds — the same 10 tests failed in every round, so nothing was load-induced or timing-flaky.

**Tests deleted:** none. No assertion was found to rest on scaffold-only rules; every failure resolved to either an implementation defect, a fixture/helper defect, or a genuine PRD non-determination that was narrowed rather than removed.

**Fixes applied to `test_helpers/`:**
- `test_helpers/assertions.py` — `assert_commitment_capacity_conserved` exempts `WITHDRAWN` commitments. The helper asserted allocated + settled + remaining == committed unconditionally, but PRD §3.2 deliberately breaks that identity on withdrawal ("the status becomes `WITHDRAWN` and `remaining_amount_cents` drops to zero"). The exemption asserts `remaining_amount_cents == 0` instead, so the withdrawal contract is still checked.

**Fixes applied to `test_suite/`** (all in the direction of greater PRD fidelity):
- `test_14_endpoints.py` — one caller of `assert_entry_types_in_order` passed bare entry-type strings while the other eight pass `(entry_type, direction)` tuples; corrected to tuples (strictly stronger, and the directions were already asserted separately).
- `test_14_endpoints.py` (clock test, 2 sites) — dropped assertions that `created_at` equals the logical-clock instant. PRD §2.4 enumerates every datetime that reads the clock and `created_at`/`updated_at` are not in the list; moreover the §2.3 ledger tie-break "`posted_at` ascending with `created_at` ascending as the tie-break" only functions if `created_at` is finer-grained than the clock. Per STEP 1c the test was split, keeping the covered `approved_at` pin and the "no business row rewritten" check.
- `test_10_entity_contracts.py` — the defaults test registered a custodian on a facility it never approved; PRD §2.8 priority 10 gates custodian registration on an `ACTIVE` facility, so the fixture now approves via a second officer first. The PRD-required `ERR_FACILITY_NOT_ACTIVE` check in the implementation was left intact.
- `test_11_state_machines.py` (covenant-waiver cascade) — BRANCH-ASYMMETRIC SIDE EFFECT. PRD §3.8 lists the waiver's cascade ("moves every `COVENANT_BREACH` margin call … to `WAIVED`") and names no ledger posting, while §3.6 pins the `MARGIN_CALL_WAIVED` entry to the direct margin-call-waiver endpoint. Whether the cascade also appends that audit-only entry is not determined. The test now accepts either ledger shape while still asserting everything PRD does determine: the funding debit is present and first, the total count matches, and any extra entry is a `CREDIT` of the exact uncured obligation (§2.6: the entry "is purely informational and moves neither balance"). The determinate direct-waiver postings remain fully asserted in `test_16_rbac.py`.

**Fixes applied to `implementation/`:**
- `workspace/implementation/routes/advances.py` — `ship_advance` returned the updated advance with HTTP 200. PRD §3.7 has shipment create a stored `BaileeLetter` in `ISSUED`, and PRD §4 states "Endpoints that create a new stored resource return HTTP 201" with "the `data` field carr[ying] the created or updated resource". Now returns `ok(bailee_letter_out(letter), 201)`. This resolved 5 of the 10 failures (four `Expected 201, got 200` plus a `KeyError: 'advance_id'` in `test_13`); confirmed no test asserts ship returns an advance, and all fixture callers use the 2xx-lenient `get_success_data`.

No endpoint, field, header, or side effect was added without a verbatim PRD sentence; no startup seeding was introduced; storage remains in-memory only.

**Orchestrator independent verification of the sweep artifacts** (this pipeline has previously seen a Step 7 subagent claim a clean sweep with no artifacts on disk): all 8 `results.{1..8}.json` exist (~34.8 KB each, written 20:18), each parses as JSON with `tests` of length 105, and the header counters read `passed=105 total=105 failed=0 errors=0 skipped=0`, durations 197–198 s. Claim confirmed.

Step 8 is NOT skipped: Step 7 ran 2 iterations with 1 `implementation/` fix, 1 `test_helpers/` fix and 4 `test_suite/` fixes.

## Step 8: Finalize PRD — 2026-09-02T20:45:42.623Z

PRD_FINALIZED.md is written.

## Line counts
- `PRD.md`: 509 lines / 110,408 bytes
- `PRD_FINALIZED.md`: 509 lines / 111,087 bytes
- Delta: 0 lines (+0.0%); 4 lines revised in place, +679 bytes (+0.61%). No inserted or deleted lines, no new sections.

## Changes
- **§2.4** — revise — added that `created_at`/`updated_at` are stamped from the server's wall clock, not the logical clock, so they never report the logical instant and are unaffected by setting the clock — `implementation/db.py:54,65` (`base_row`/`touch` both use `wall_now()`).
- **§3.7** — revise — pinned that the shipment endpoint's `data` carries the created `BaileeLetter` (not the updated advance) with HTTP 201, and that the re-shipment self-loop behaves the same — `implementation/routes/advances.py:537`.
- **§3.8** — revise — pinned that the covenant-waiver's `COVENANT_BREACH` margin-call cascade writes no ledger entry, the `MARGIN_CALL_WAIVED` posting belonging to the margin-call waiver endpoint alone — `implementation/routes/covenant_tests.py:35-41` vs `implementation/services/states.py:150`.
- **§4 table, `POST /advances/{id}/ship`** — revise — "Returns the created bailee letter." appended, so the §4 preamble's "unless the endpoint's description says otherwise" resolves correctly — `implementation/routes/advances.py:537`.

## Per-edit pre-edit search log

**Edit 1 (§2.4 timestamps)**
- (a) Subject: the source of every `created_at`/`updated_at` value, and what else does/doesn't read the wall clock.
- (b) Enumerated: `db.py:50-59` `base_row` (wall stamp, also used with `with_version=False` for `LedgerEntry`/`CurePayment`), `db.py:62-67` `touch` (wall stamp on every mutation, incl. cascades), `clock.py:83` `wall_now`, `clock.py:33-41` `fmt_dt`; grepped all writers/readers of `created_at`/`updated_at` across `implementation/` — `serializers.py` only echoes the stored strings, `response.py:12` `api_request_timestamp` is also wall-clock, and `computed.py:63-73/353-356` plus `db.by_created_at` use `created_at` only as a sort key, never compared to the clock.
- (c) Adjustment: deliberately did **not** claim these are the *only* non-logical-clock datetimes, because `api_request_timestamp` is wall-clock too; scoped the sentence to `created_at`/`updated_at` alone. Also placed it in §2.4's identity paragraph rather than the logical-clock paragraph so it does not contradict "All time-dependent behaviour reads a logical clock", whose enumerated list already omits these two fields.

**Edit 2 (§3.7 shipment response)**
- (a) Subject: what resource and status code each mutating endpoint returns, especially endpoints that create one row while updating another.
- (b) Enumerated: every `return ok(...)` in `implementation/routes/` (39 sites). Creators returning 201 with their primary created row: `advances.py:247`, `:433`, `:673`, `facilities.py:129,251,287,326,397,478`, `margin_calls.py:68,108`. Ship at `advances.py:537` is the sole endpoint whose 201 body is a *secondary* created row. Confirmed `ship_advance` is the only `BaileeLetter` producer (single `db.bailee_letters[` write site) and that the re-ship self-loop goes through the same handler.
- (c) Adjustment: scoped the claim strictly to the shipment endpoint, avoiding any general re-statement of the §4 preamble rule that would mis-describe `POST /advances` or `POST /advances/{id}/receipts`; explicitly extended it to the re-shipment self-loop since that path shares the handler.

**Edit 3 (§3.8 covenant-waiver cascade)**
- (a) Subject: which operations post a `MARGIN_CALL_WAIVED` entry, and which margin-call status changes post no ledger entry.
- (b) Enumerated: grepped every `post_entry` callsite — `advances.py:349` (ADVANCE_FUNDED), `:583` (INVESTOR_PROCEEDS), `:619` (REPURCHASE), `cure.py:70,74` (FEE_PAYMENT, CURE_PRINCIPAL), `aging.py:71` (FEE_ACCRUAL), `states.py:150` (MARGIN_CALL_WAIVED). Traced `states.waive_call` → sole caller `margin_calls.py:136`. Checked every other margin-call status writer: `covenant_tests.py:40` (→WAIVED, no posting), `states.close_calls:112` (→CURED, no posting), `aging.py` defaulting (→DEFAULTED, no posting), and `create_margin_call` (`states.py:82-102`, no posting).
- (c) Adjustment: wrote "writes no ledger entry **of its own**" and confined the exclusivity clause to `MARGIN_CALL_WAIVED`, so the sentence stays true of the surrounding covenant-waiver request without implying anything about the `CURED` closures in §3.6. Left `waived_by_user_id` on cascade-waived calls unmentioned (impl leaves it null) — not a Step 7 site, and under-determination is preferable to an out-of-scope pin.

**Orchestrator verification:** both files are 509 lines; whitespace-normalised diff shows 8 changed lines total (4 revised line-pairs), consistent with the reported 4 in-place revisions; `PRD_FINALIZED.md` ends at the same complete §5 table boundary as `PRD.md`.

## Step 9: Complete PRD — 2026-09-02T21:05:38.563Z

`PRD_COMPLETED.md` is written and complete (ends at the real §5 error-code table boundary, last row `| ERR_PRODUCT_SUBLIMIT_EXCEEDED | 422 |`).

**File:** `workspace/PRD_COMPLETED.md`

- Source `PRD_FINALIZED.md`: 509 lines, 111,087 chars
- `PRD_COMPLETED.md`: 509 lines, 123,016 chars (char-delta **+11,929**)
- 38 lines changed, all in-paragraph; zero new lines, zero new sections, zero new paragraphs
- Counts: **21 ambiguity-pins**, **17 mismatch-revisions**

Changes:

- §2.1 — revise — mismatch — Borrower advance list is silently narrowed, not refused; reading one custodian is not ownership-checked; the pri-4 comparison happens at exactly those enumerated operations, so reading a commitment, withdrawing one and raising a demand are unchecked — `routes/advances.py:119-126`, `routes/commitments.py:24-28`
- §2.3 — revise — mismatch — ordering tie-break is the server's insertion sequence, not `id`, on advances/lists/ledger — `db.py:70-71`
- §2.3 — insert — ambiguity — full filter inventory (exact-string, unknown params ignored, `is_aged` spellings, per-endpoint `status`/`investor_id`/`advance_id`/`entry_type`/`direction`/`trigger_reason`/`reason`) — `middleware.py` `filter_by`/`q_bool`, `routes/*.py`
- §2.4 — insert — ambiguity — `current_utc` required, ISO-8601 or `ERR_VALIDATION`, both values echoed verbatim; first `previous_utc` is `2026-08-01T00:00:00Z` — `clock.py:1-40`
- §2.6 — insert — ambiguity — `investor_exposures` carries one entry per registered investor regardless of status, zero included, `created_at` ascending — `serializers.py:311-315`
- §2.8/5 — revise — ambiguity — receipt filing's `custodian_id` and shipment's `investor_id` join the body-existence tier — `routes/advances.py:373-377,483-487`
- §2.8/6 — insert — ambiguity — tier skipped when `product_code` is absent/unrecognised; falls through to `ERR_VALIDATION` — `routes/advances.py:156-163`
- §2.8/7 — insert — ambiguity — the six free-text `reason` fields (raw-length ≥1, ≤500), demand `reason` is an enum, manual call has none, `callback_reference`/`proceeds_reference` ≤200, `block_reason` ≤100 and non-`OPERATOR_BLOCK` fails here, `cure_days` ≥0, version tokens ≥0 — `validation.py:39-51`, `routes/wires.py:32-40`
- §2.8/10 — insert — ambiguity — investor approval refused with `ERR_FACILITY_NOT_ACTIVE` only while facility is `SUSPENDED` — `routes/investors.py:32-48`
- §2.8/12 — revise — mismatch — cure gate reads the receipt's own `EXCEPTION` status; duplicate settled receipt and shipment's file-in-hand check share `ERR_CUSTODY_INVALID_STATE` — `routes/receipts.py:34-37`, `routes/advances.py:395-398,494-498`
- §2.8/18 — revise — mismatch — reinstatement gate is four conditions (open calls, `DEFAULTED` call, *latest* covenant status, escalated demands) — `routes/facilities.py:194-199`, `services/computed.py:353-366`
- §2.8/25 — revise — mismatch — only two operations are investor-approval-guarded; purchase is not — `routes/advances.py:503-506,550-597`
- §2.10 — insert — ambiguity — facility `version` moves twice when a request both mutates rows and flips posture — `routes/demands.py:30-33`, `routes/advances.py:640-641`, `routes/covenant_tests.py:43-44`
- §3.1 — revise — mismatch — the wet bucket counts only wet advances whose file is still outstanding (`PENDING_RECEIPT`/`RECEIPT_OVERDUE`) — `services/computed.py:282-294`
- §3.2 — insert — ambiguity — orphan cascade issues its `COMMITMENT_WITHDRAWN` call unconditionally, so two open calls can coexist — `services/states.py:120-135`
- §3.2 — revise — mismatch — withdrawal only from `OPEN`/`PARTIALLY_ALLOCATED`, and the `Investor` identity is not compared — `routes/commitments.py:24-38`
- §3.3 — insert — ambiguity — `provisional_advance_amount_cents` computed at booking from stages one–three; `market_value_cents` echo tolerance; three valuation figures start at zero — `routes/advances.py:215-227`
- §3.3 — insert — ambiguity — `block_reason` ≤100 and the non-`OPERATOR_BLOCK` refusal precedes the wire-state check — `routes/wires.py:32-45`
- §3.3 — revise — mismatch — the commitment's status, `product_code` and window are never validated at booking or funding; only priority 43 applies — `routes/advances.py:146-155,288-360`
- §3.4 — revise — mismatch — stages one–three also run at booking and are re-run from scratch at funding — `services/sizing.py:25-33`, `routes/advances.py:225-227`
- §3.5 — insert — ambiguity — duplicate settled receipt reports `ERR_CUSTODY_INVALID_STATE` — `routes/advances.py:395-398`
- §3.5 — insert — ambiguity — `RECEIPT_OVERDUE → RECEIVED_EXCEPTION` is permitted — `routes/advances.py:424`
- §3.5 — insert — ambiguity — `cured_exception_codes` required non-empty enum array; gate is the receipt's own status; union appends codes outside `exception_codes` — `routes/receipts.py:32-47`
- §3.6 — insert — ambiguity — last-held rate defaults to zero, and all valuation figures plus `outstanding_balance_cents`/`dwell_days`/`is_aged` are recomputed on every read without bumping `version` — `serializers.py:122-153`
- §3.6 — insert — ambiguity — manual `cure_days` ≥0; advance-level amount from a fresh stored valuation; any funding state accepted — `routes/margin_calls.py:53-63`
- §3.6 — insert — ambiguity — `principal_allocation` lists every covered advance, zero amounts included — `services/cure.py:39-56`
- §3.6 — insert — ambiguity — covered advances are re-valued after the payment — `services/cure.py:86-87`
- §3.7 — revise — mismatch — shipment's check order and codes (`ERR_CUSTODY_INVALID_STATE` before `ERR_BAILEE_WINDOW_OVERLAP` before approval/mismatch, then `ERR_OPEN_MARGIN_CALL`) — `routes/advances.py:489-513`
- §3.7 — revise — mismatch — re-shipment requires only no `ISSUED` letter covering the clock, not all letters `EXPIRED`/`REVOKED` — `routes/advances.py:99-104,500`
- §3.7 — insert — ambiguity — purchase does not re-check investor approval, settles the newest live letter (the caller's own when acting as `Investor`, else `ERR_RESOURCE_MISMATCH`), zero outstanding → `ERR_ADVANCE_INVALID_STATE`, other live letters untouched — `routes/advances.py:550-586`
- §3.8 — insert — ambiguity — a `period_end` earlier than the latest stored is `ERR_VALIDATION`, tested before the duplicate check — `routes/facilities.py:438-447`
- §3.8 — revise — mismatch — suspension fires at `consecutive_breach_count` ≥2 from whatever posture the facility holds — `routes/facilities.py:472-478`
- §3.8 — revise — mismatch — the same, restated in the posture summary's "three ways" list — `routes/facilities.py:472-478`
- §3.9 — revise — mismatch — `margin_calls_issued` counts every call the run created across all three trigger reasons — `services/aging.py:94-98,135-139,155-159`
- §3.9 — revise — mismatch — newly overdue wet files get guarded `CUSTODY_EXCEPTION` calls; commitment expiry covers `OPEN` **or** `PARTIALLY_ALLOCATED`, re-values in the same run and issues guarded `COMMITMENT_WITHDRAWN` calls — `services/aging.py:130-157`
- §3.9 — insert — ambiguity — `last_accrual_at` advances (bumping `version`) even at zero/negative `accrual_days` unless already equal; a null baseline accrues nothing and stays null — `services/aging.py:44-54`
- §4 — revise — mismatch — reinstate row now states the full four-condition gate — `routes/facilities.py:194-199`
- §4 — revise — mismatch — `GET /advances` row: insertion-sequence tie-break and Borrower narrowing — `db.py:70-71`, `routes/advances.py:250-266`

**Orchestrator verification:** `PRD_COMPLETED.md` is 509 lines / 123,016 chars, all five `## ` section headings intact at lines 3/11/226/388/451, ends at a complete §5 table row; `diff` against `PRD_FINALIZED.md` shows exactly 38 changed lines with no line-count change, matching the reported 21 + 17 = 38 in-paragraph edits. Final tree contains `SCAFFOLD.yaml`, both design yamls, `test_helpers/`, `test_suite/`, `worklog.md`, and `workspace/` with `INSTRUCTION.md`, `PRD.md`, `PRD_FINALIZED.md`, `PRD_COMPLETED.md`, `sweep.log`, and `implementation/` (incl. the 8 passing `results.{1..8}.json`).

**Pipeline complete.** Step 9 produced `workspace/PRD_COMPLETED.md`; no further steps remain. Notable observation for upstream feedback: Step 9 found 17 genuine PRD/implementation mismatches that the 105-test suite never exercised (most concentrated in §2.1 role scoping, §3.7 shipment/purchase check ordering, §3.8 breach-count escalation and §3.9 aging-run counters) — a signal that the corner index under-covers read-path scoping and aging-run summary fields relative to the write-path depth it covers well.
