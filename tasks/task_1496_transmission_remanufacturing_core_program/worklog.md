# Worklog — task_1496_transmission_remanufacturing_core_program

## Step 1: Create Task Directory — 2026-08-13T13:21:22.000Z

Pre-created by pipeline harness (tasks/task_1496_transmission_remanufacturing_core_program/ + workspace/); index scan skipped per instructions.

## Step 2: Generate Scaffold — 2026-08-13T14:35:00.000Z

All checks pass. The scaffold is complete and lint-clean.

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_1496_transmission_remanufacturing_core_program/`):
- `SCAFFOLD.yaml` — §1.0–§1.7 only (no difficulty/corner keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top-level key `scaffold_difficulty_design`
- `SCAFFOLD_CORNER_DESIGN.yaml` — single top-level key `scaffold_corner_design`

**Design choices**: workflow-orchestration primary archetype with ledger-reconciliation secondary (core deposit lifecycle); flat entity topology under `/api`; cyclic state machines (reman rework loop, invoice dispute/re-inspection cycle); segregation-of-duties role model (calibration verifier != drafter); logical-clock endpoint with fixed default `2026-08-01T00:00:00Z`.

**SCAFFOLD.yaml counts**:
- 9 entities: TransmissionModel, HardPart, InterchangeMapping (M2M junction), RemanOrder, DynoBooking, DynoTestRun, CoreUnit, CoreDepositInvoice, WarrantyClaim (with parallel `claim_status` × `return_status` dimensions)
- 42 endpoints (incl. `POST /api/_clock/set_current_utc`), 42 error codes, 6 calculations, 5 state-machine entries, 10 validation priorities, 11 roles, 2 OCC concurrency rules (`resync-spec` on RemanOrder.version, `stock-adjustments` on HardPart.version)

**SCAFFOLD_DIFFICULTY_DESIGN.yaml**: 18 instances, exactly 2 per rule × 9 rules, each with structured `setup_api_calls`/`trigger` chains and pre-computed literal asserts (verified arithmetic: e.g., provisional 40000 vs final 50000 credit; BOOK 72000 vs ACTUAL 60000 labor; dyno 89.98 MARGINAL vs 90.00 PASS boundary; day-30 on-time vs day-31 late; depth-3 dyno-fail → release → promote cascade).

**SCAFFOLD_CORNER_DESIGN.yaml**: 51 instances total — 44 active (entities/state-machines/calculations/validations/endpoints/errors/rbac/complexity-layers/consistency sections, including 13 error-trigger corners covering every catalog error) + 7 `excluded_because` stubs citing difficulty instances.

**Verification**: `scaffold_lint.py` verdict — `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (42 endpoints, 9 entities, 18 §1.8 + 44 §1.9 active instances, 577 calls scanned). Additional scripted checks: zero duplicate instance names across both files, all `grounds` references resolve to declared §1.1–§1.7 elements, all `excluded_because` refs resolve, no forbidden concurrency vocabulary. One unreachable error (`ERR_INVOICE_ALREADY_HAS_CORE`) was found during self-review and removed from the catalog. No sibling task directories were inspected.

## Step 3: Copy Shared Files — 2026-08-13T14:35:10.000Z

Copied ./INSTRUCTION.md to workspace/INSTRUCTION.md.

## Step 4: Generate PRD — 2026-08-13T15:00:00.000Z

PRD generated at `/home/ubuntu/github/CodingPRD/tasks/task_1496_transmission_remanufacturing_core_program/workspace/PRD.md`. The withheld files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were never opened or referenced.

**Output**: 293 lines, single file ending at §5 with no audit footer.

**Section list**:
- §1 Introduction (2 paragraphs)
- §2 Global Specifications: 2.1 RBAC, 2.2 API Response Structure (byte-identical verbatim block), 2.3 Pagination, 2.4 Common Resource Properties, 2.5 The Logical Clock, 2.6 Money/Scores/Rounding, 2.7 OCC, 2.8 Request Validation Pipeline (10-stage ordered), 2.9 Inventory Conservation & Promotion Scan, 2.10 Build-Spec Pinning & Model Versioning
- §3 Business Logic (8 subsections): 3.1 Catalog Foundations, 3.2 Order Creation & Kit Reservation, 3.3 Assembly/Calibration/Resync/Cancel, 3.4 Dyno Testing & Rework Cycle, 3.5 Shipping & Deposit Invoice, 3.6 Core Intake/Grading/Settlement, 3.7 Disputes/Re-Inspection/Adjustment, 3.8 Warranty/Labor Allowance/Defective Returns
- §4 Endpoint table (42 rows, 4 columns), §5 Error catalogue (42 rows, 2 columns)

**Hard-contract reports**:

```
Field coverage check:
- entities[].fields: 75 required, 75 present, 0 missing (1 initial miss, routing_type, repaired)
- endpoints[].request_body: 44 required, 44 present, 0 missing
- endpoints[].query_params: 10 required, 10 present, 0 missing
- path params ({id}): 1 required, 1 present
- enum/state values: 56 checked, 0 missing; roles: 11/11; error ids: 42/42
Status: PASS

Rule coverage check:
- validations[] priority ordering: 10 stages expressed as an ordered pipeline in §2.8 with worked orderings (verify-calibration, stock-adjustments, dyno runs, core registration)
- concurrency_rules[]: 2/2 expressed — resync-spec (expected_reman_order_version) and stock-adjustments (expected_hard_part_version), both naming ERR_STALE_VERSION/412, no race framing
- state_machines[].transitions: 28/28 expressed (RemanOrder 14, CoreUnit 6, Invoice 8, Claim 3, Return 3 — incl. all four cancel branches and four dyno verdict branches with symmetric density)
- calculations[]: 6/6 expressed in precise prose (0.8 provisional factor; finding weights 20/25/10/15/5 with grade maxes 5/15/30 and multipliers 1.0/0.75/0.5; 30/45-day late tiers at 1.0/0.75/forfeit; dyno penalty 2.0/kPa with pinned per-gear-rounding-first order, 90.00/80.00 verdict bands, 3-attempt budget; BOOK_HOURS vs ACTUAL_HOURS variants with cap-equality rule; routing selector top-down with inclusive 50000-cent threshold; waterfall allocation ranking DIRECT-then-ADAPTED, unit_cost_cents ASC, created_at ASC tie-break)
- endpoints[].side_effects / applies_to: all 42 endpoints' side effects narrated; validation applies_to scopes enumerated in §2.8
- entities[].fields[] structured content: defaults (warranty_days 365, qty_reserved 0, order initial statuses), null-until fields (tcm_flash_version_applied, last_shift_quality_score, grade, final/forfeited credits, labor_allowance_cents, deny_reason), computed fields all reconstructible
- sibling-branch symmetry: 8 groups checked (cancel×4, dyno verdicts×4, REINSPECT/ADJUST, grade bands, routing rules, allowance variants, late tiers, inspect from RECEIVED/RE_INSPECTION), 0 asymmetric
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 407
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

**Coverage-audit notes**: (1) Fuzzy-word scan clean; no operator syntax (`==`, `>=`, `+=`, AND/OR/IN) in §3 prose — all formulas translated to natural language passing the reconstruction test. (2) §2.2 confirmed byte-identical to the canonical block. (3) The scaffold's per-error HTTP status exception (`ERR_DYNO_ATTEMPT_EXHAUSTED` = 422 amid the 409 constraint family) is honored in §5. (4) Constants embedded in business context (72 hours, 30 surcharge minutes, 30/45 days, 50000 cents, 365-day default warranty, 2026-08-01T00:00:00Z clock default). (5) Request parameters are scattered across ≥2 subsections where the skill requires (e.g., `qty_delta` in §3.1 vs `expected_hard_part_version` in §2.7/§3.1; claim fields split across §3.8 paragraphs).

## Step 6: Generate Implementation — 2026-08-13T15:22:00.000Z

Implementation complete. Here is the summary.

## Files written (13 source files, all under `tasks/task_1496_transmission_remanufacturing_core_program/workspace/implementation/`)

- `start.sh` — executable foreground launcher; guards `pip install` behind `python3 -c "import flask"` so per-test reboots skip reinstall; `exec python3 app.py`
- `requirements.txt` — `flask>=3.0,<4.0`
- `app.py` — Flask entry point, blueprint registration, `ApiError`/404/405/fallback handlers; binds `0.0.0.0:$PORT` (default 10000)
- `db.py` — in-memory `Store` (9 entity dicts); logical clock initialized to exactly `2026-08-01T00:00:00Z`; **no seeding anywhere**
- `errors.py` — all 37 error-ID constants from the scaffold catalog
- `response.py` — envelope `{meta: {api_request_id ("req_"+20 alnum), api_request_timestamp (3-frac-digit ISO UTC)}, response_type, data}`; pagination fields (`limit/offset/total_count/has_more`) inside `meta`; error envelope with `data.error_id`/`data.message`
- `middleware.py` — `X-User-ID`/`X-User-Role` presence check (400) then role permission (403); `Any` wildcard for reads
- `validators.py` — body-shape checks (`ERR_INVALID_REQUEST`), ISO-8601 parsing, 3-frac-digit timestamp formatting, `limit`/`offset` parsing with defaults 10/0 and clamping (min 1, max 100)
- `routes/models.py`, `routes/hard_parts.py`, `routes/interchange.py`, `routes/orders.py`, `routes/dyno.py`, `routes/cores.py`, `routes/warranty.py`, `routes/clock.py`
- `services/serializers.py`, `services/allocation.py` (waterfall allocation + created_at-ASC promotion scan), `services/calculations.py` (all money math via `Decimal` ROUND_HALF_UP; dyno per-gear penalty rounded to 2dp before summing, per the pinned rounding order)

## Endpoints implemented: 41/41 from the scaffold table
3 TransmissionModel, 3 HardPart, 3 InterchangeMapping, 10 RemanOrder (incl. kit-reserve, complete-assembly, calibration PUT, verify-calibration, resync-spec, ship, cancel), 3 DynoBooking, 3 DynoTestRun, 4 CoreUnit, 4 CoreDepositInvoice (incl. dispute/resolve-dispute), 8 WarrantyClaim (incl. approve/deny/pay/return-ship/return-receive), 1 logical-clock endpoint. Key fidelity points: OCC on resync (`expected_reman_order_version`) and stock-adjustments (`expected_hard_part_version`) returning 412 `ERR_STALE_VERSION`; validation pipeline ordering (body-shape → existence → OCC → state → SoD → temporal → constraint → fiscal); segregation-of-duties on verify; 72h calibration staleness; half-open dyno-cell windows; closed dock intervals + 30-min buffer; all-or-nothing kitting with PART_HOLD promotion scan on every availability-increasing event; ship cascade creating the invoice with `round_half_up(0.8·deposit)` provisional credit; grade/late-factor settlement bands; dispute → REINSPECT/ADJUST; BOOK_HOURS vs ACTUAL_HOURS allowance with inclusive cap; routing selector (ELECTRICAL_TCM → DISTRIBUTOR, ≥50000 → PLANT, else LOCAL_SCRAP); return-leg ownership check on return-ship.

## Boot verification
`bash start.sh` from `implementation/` boots cleanly in ~1s and answers HTTP 200. Fresh-boot store confirmed empty (orders/mappings/invoices all `total_count: 0`). Ran four smoke suites (~90 assertions) covering auth, RBAC, CRUD, kitting shortage/promotion, OCC staleness, SoD, dyno scoring bands (PASS/MARGINAL/FAIL, attempt exhaustion, ENGINEERING_REVIEW release+promotion), ship→invoice→inspect→settle (FULL/PARTIAL/FORFEITED), dispute→REINSPECT→re-inspect, ADJUST, warranty allowance variants/cap/routing, return leg with ownership, warranty window expiry, clock default/advance, and pagination — all pass (two apparent failures in one suite were test-script artifacts: my script assumed a stale clock value, and the server's actual computed values were verified correct by the targeted re-tests).

## Step 5: Generate Unit Tests — 2026-08-13T15:45:00.000Z

Generation complete. Summary:

## Generated output

**`test_helpers/` (Stage 1, 9 files, 1245 lines)** — under `/home/ubuntu/github/CodingPRD/tasks/task_1496_transmission_remanufacturing_core_program/test_helpers/`:
- `types.py` — 16 enums + 9 TypedDicts; the three immutable records (InterchangeMapping, DynoBooking, DynoTestRun) correctly omit `updated_at`/`version` per PRD §2.4
- `api_client.py` — 41 endpoint methods covering all PRD §4 endpoints including `/api/_clock/set_current_utc`
- `api_errors.py` — all 42 error IDs with HTTP statuses, registered via `set_error_http_status_map`
- `assertions.py` — per-entity assertions + `assert_hard_part_availability` and `assert_deposit_invariant` domain invariants
- `factories.py`, `constants.py` (all PRD thresholds: grade bands 5/15/30, late tiers 30/45, 0.8 provisional, 2.0 kPa penalty, 90/80 verdict bands, 3-attempt budget, 50000c routing threshold, 72h cal age, 30-min dock buffer)
- `test_users.py` — 12 header constants (incl. dual Calibrators `cal-a`/`cal-b` for SoD, `inst-1` for installer ownership) + per-instance builders
- `fixtures.py` — composite drivers: `drive_order_to_calibration/dyno_queue/shipped`, `fail_run_and_recalibrate`, `setup_third_fail_cascade`, `setup_attempt_budget_order`, `setup_kitted_pair`/`setup_single_part_hold_order`, `setup_graded_core`/`setup_disputed_invoice`, `setup_submitted/approved_claim`/`setup_claim_in_transit`, `setup_salvage_promotion_scenario`, `get_invoice_for_order`, `set_clock`

**`test_suite/` (Stage 2, conftest + 8 files)** — under `/home/ubuntu/github/CodingPRD/tasks/task_1496_transmission_remanufacturing_core_program/test_suite/`: test_01 catalog/inventory/interchange, test_02 order lifecycle/spec pinning, test_03 dyno/shipping, test_04 core intake/grading/settlement, test_05 disputes/adjustments, test_06 warranty/returns, test_07 security/404s, test_08 listings/pagination.

## Coverage (81 tests total)

- **Queue A (Difficulty): 36 tests — all 18 instances × ≥2 tests each.** Second tests split each instance's assertion surface (e.g., provisional-vs-final split into issuance-time and post-grading tests; priority-pair instances get the conflict test plus an isolation test proving the losing error fires alone).
- **Queue B (Corner): 45 tests — all 44 non-stub instances ≥1 test each** (grade-boundary instance split into two tests). All 7 `excluded_because:` stubs left untranslated; every stub's `difficulty_instance` pointer verified to resolve.

## Instances skipped

**None.** Every instance passed the PRD-first two-condition filter — all asserted rules (including both priority-pair orderings, the OCC rules, and every asserted `error_id`) have verbatim PRD coverage (§2.7, §2.8's explicit ordering prose, §3.x).

## Stage 2 self-checks (all automated, all pass)

- 81/81 tests collect under pytest; all files compile
- Tag audit: exactly one `Design:` line per test, always the last docstring line, every tag resolves to a real instance in the source yaml
- Verbatim pass: 124 docstring quotes, each has a ≥8-word substring surviving literal grep of PRD.md
- No `skip`/`skipif`/`xfail` markers; no "scaffold" references in generated code
- All 31 asserted `error_id`s appear in PRD prose (not merely the §5 table)

**Judgment call to note:** the corner instances `model_create_applies_defaults` and `order_create_applies_system_defaults` also listed `version == 1` assertions; PRD §2.4 never states the version counter's starting value (only that it increments), so that one literal sub-assertion was dropped per the two-reader rule. OCC tests instead capture the created version and assert exact `+1` increments, which PRD §2.7/§3.3 uniquely derive.

## Step 7: Run Tests and Iterate — 2026-08-13T16:10:00.000Z

All 8 rounds pass 81/81 with zero failures and zero errors. The exit condition is met.

---

## Summary

**Iterations run:** 3 eight-round parallel sweeps (initial diagnostic sweep + 2 fix-verification sweeps). Final sweep: all 8 rounds at 81/81 passed, 0 failed, 0 errors.

**Tests deleted:** None.

**Fixes applied to `test_helpers/`:**
- `/home/ubuntu/github/CodingPRD/tasks/task_1496_transmission_remanufacturing_core_program/test_helpers/fixtures.py` — `setup_registered_core()` gained a `cell` passthrough parameter (default `"DYNO-1"`) forwarded to `drive_order_to_shipped`. Why: callers building two shipped orders in one test booked identical dyno windows on the same cell, and the PRD-faithful implementation correctly rejected the second booking with `ERR_DYNO_CELL_OVERLAP` (PRD §3.4 half-open cell windows). The helper now exposes the same cell parameter the sibling pattern (`_two_shipped_orders`) already used.

**Fixes applied to `test_suite/`:**
- `/home/ubuntu/github/CodingPRD/tasks/task_1496_transmission_remanufacturing_core_program/test_suite/test_04_core_intake_grading_and_settlement.py` — `test_full_settlement_closes_order_partial_does_not`: the setup called `setup_registered_core()` twice with no shared model, so each leg created a `MIN-6L80` model and the second create was correctly rejected under PRD §3.1 ("a `model_code` unique across all models"). The asserted rule itself (SETTLED_FULL closes the order's `core_settlement_status`, SETTLED_PARTIAL leaves it PENDING) is verbatim in PRD §3.6/§3.7, so the test was kept and the setup fixed to share one model with distinct docks and distinct dyno cells.
- Same file — `test_dock_start_after_buffer_accepted`: the test asserted acceptance of a dock appointment starting at *exactly* prior end + 30 minutes. PRD §3.6 ("Dock appointments occupy closed intervals, and each appointment carries a 30-minute turnaround buffer appended after its end; a new appointment whose closed interval conflicts with an existing appointment's buffer-padded occupancy... is rejected") does not uniquely determine the boundary: one faithful reading treats the buffer-padded occupancy as the closed interval [start, end+30m] (the boundary instant is occupied → conflict), another treats the buffer as a gap requirement satisfied by exactly 30 minutes (→ accept). STEP 1b unique-derivability collapse (boundary-precision silence). Per STEP 1c, the test was split: the underdetermined exact-boundary assertion was removed, and the covered assertions (successful registration → 201, core `RECEIVED`, invoice flips `OPEN` → `AWAITING_GRADE` — both verbatim in PRD §3.6) were kept with the second appointment moved strictly clear of the buffer (12:00–13:00). The sibling rejection test (`test_dock_start_at_prior_end_rejected`, start == prior end) is uniquely derivable from "closed intervals" alone and was untouched.

**Fixes applied to `implementation/`:** None. Every failure traced to test-side precondition or boundary-derivability bugs; the implementation was PRD-faithful in all cases (model-code uniqueness, dyno-cell overlap, and dock-overlap rejection all behave per PRD prose).

## Step 8: Finalize PRD — 2026-08-13T16:15:00.000Z

Done. PRD_FINALIZED.md is written at `/home/ubuntu/github/CodingPRD/tasks/task_1496_transmission_remanufacturing_core_program/workspace/PRD_FINALIZED.md` with exactly one in-place revision.

## Line counts and delta

- `PRD.md`: 292 lines; `PRD_FINALIZED.md`: 292 lines — 0.0% line-count delta (one sentence revised inline within line 178; no lines added or removed).

## Changes

- **§3.6 (Core Intake, Inspection, and Graded Settlement) — revise** — Pinned the boundary precision of the dock-overlap rule: the buffer-padded occupancy of an existing appointment is the **closed** interval from its `dock_start_utc` through its `dock_end_utc` + 30 minutes inclusive, and a new appointment sharing *any instant* with that occupancy conflicts — explicitly including a new appointment starting at exactly `dock_end_utc` + 30 minutes. — `implementation/routes/cores.py:117-121` (`occ_end = c["dock_end_utc"] + DOCK_BUFFER` with `dock_start <= occ_end and occ_start <= dock_end`, i.e., `<=` on both ends).

The other two Step 7 items required no edit:
- `test_helpers/fixtures.py` cell passthrough — pure fixture bug; dyno half-open overlap is already uniquely pinned by PRD §3.4 and impl `routes/dyno.py:63` (strict `<` comparisons) matches.
- `test_04` model sharing — pure test-setup bug; PRD §3.1 already pins "a `model_code` unique across all models" and impl `routes/models.py:76-77` enforces it.

## Per-edit pre-edit search log

**Edit 1 (§3.6 dock-overlap boundary):**
- **(a) Subject:** dock-appointment conflict semantics — boundary inclusivity, check asymmetry, and status scope of "existing appointment".
- **(b) Paths enumerated:** grep for `dock_start_utc|dock_end_utc|dock_code|DOCK_BUFFER|DOCK_OVERLAP` across all of `implementation/` (excluding `__pycache__`). Behavioral site: `routes/cores.py:87-152` (`register_core`) — the conflict loop at lines 114-126 runs at registration time against **every** existing core on the same dock with no status filter, pads only the *existing* appointment's end by 30 minutes (`DOCK_BUFFER`, line 29), and uses `<=` on both comparisons, so both touch-directions conflict (new start == existing padded end; new end == existing start). Read-only exposure: `services/serializers.py:110-112`. Constant: `errors.py:59`. No other endpoint reads or mutates dock windows.
- **(c) Wording adjustment:** phrased as "shares any instant … inclusive of that final instant" rather than "starting at or before … plus 30 minutes" alone, because the impl's `<=` applies symmetrically to both interval ends (a new appointment *ending* exactly at an existing appointment's start also conflicts); kept the existing sentence's asymmetry (only the existing appointment is buffer-padded — the new appointment's own trailing buffer is not part of the check, verified at `cores.py:121`) and kept "an existing appointment" status-blind to match the unfiltered loop. The explicit "starting at exactly … plus 30 minutes is rejected" clause pins the exact boundary the Step 7 test had asserted as accepted.
