# Worklog — task_0153_car_rental_operations

Scenario: Car Rental Operations: fleet/class availability, reservation/upgrade, daily/weekly rate + LDW/PAI add-ons, mileage/fuel policy, damage/incident, loyalty, one-way drop fee, young-driver surcharge, no-show grace

Difficulty: EXPERT (§0.4 Expert band) — applied to Step 2 only.

## Step 1: Create task directory — 2026-06-04T18:41:54.000Z

Created `tasks/task_0153_car_rental_operations/` and `tasks/task_0153_car_rental_operations/workspace/` (pre-allocated index per orchestration override; no auto-scan).

## Step 2: Generate scaffold (Expert) — 2026-06-04T18:41:54.000Z

Generated all three Expert-band scaffold artifacts. Scaffold linter returns **`VERDICT: clean lint`** (zero violations across 359 setup/trigger calls; all FK reverse-reachability satisfied). All three files written and YAML-parse-clean (SCAFFOLD.yaml 1231 lines, DIFFICULTY 1066, CORNER 1130).

**Scaffold composition**
- **Entities: 10** — Location, VehicleClass, RatePlan, Vehicle, LoyaltyMember, Reservation, RentalAgreement, IncidentReport, LedgerEntry, LoyaltyAccrual (flat topology, FK-linked).
- **State machines: 4** — Reservation (branching fork from CONFIRMED → {PICKED_UP, NO_SHOW, CANCELLED}), Vehicle (cyclic AVAILABLE↔RESERVED plus ON_RENT→{AVAILABLE,MAINTENANCE,RETIRED}), RentalAgreement (OPEN→{CLOSED,WRITE_OFF}), IncidentReport (FILED→{RESOLVED,VOID}).
- **Calculations: 7** — reservation_quote (tiered, RatePlan-override selector), agreement_settlement (dual-variant provisional/final), incident_liability (LDW-waived/no-LDW variants), loyalty_accrual (close-full/writeoff-half, order-pinned floor), member_tier, no_show_policy, class_availability_reconcile.
- **Validations: 21** (priority-ordered, auth → existence → state → OCC → business safety/temporal/fiscal/referential).
- **Endpoints: 44** — business surface plus reverse-reachability GETs and two `/_` test-driving endpoints (`/_clock/set_current_utc`, `/_members/{id}/set_loyalty`). Exceeds Expert 20–32 band because FK reverse-reachability forces thin list/sub-resource GETs; overage accepted since lint is clean. `api_prefix` set to `""`.
- **Errors: 21.** **Roles: 3** — FleetManager (opaque), RentalAgent (opaque), Member (entity_backed:LoyaltyMember); peer_roles model. **Concurrency rules: 1** — OCC on Vehicle.version (412).

**Expert-band instance counts**
- §1.8 difficulty: **18 instances** = 9 rules × 2 each.
- §1.9 corner: **30 instances** across entities, state_machines, calculations, validations, endpoints, errors, rbac, cross_cutting_complexity_layers, consistency_model.

All formula-derived assertions computed in code and pinned as literals (quote 69700, settlement 20500, fuel-low 19500, SILVER accrual 410, incident LDW 100000 vs no-LDW 300000). One numeric fix caught during review (one-way drop fee keys off dropoff location → 69700).

## Step 3: Copy shared files — 2026-06-04T18:41:54.000Z

Copied `./INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-04T18:41:54.000Z

Generated `workspace/PRD.md` (271 lines). Design files (DIFFICULTY/CORNER) were withheld and not read.

**Major sections:** §1 Introduction (pricing-engine + quota-allocation framing), §2 Global Specs (9 subsections: RBAC, response envelope, pagination, common properties incl. append-only LedgerEntry/LoyaltyAccrual, denormalized availability reconciliation, nested-retrieval validation, 5-gate validation priority order, monetary precision/rounding, OCC on vehicle holds), §3 Business Logic (10 lifecycle subsections), §4 Endpoint table (40 endpoints), §5 Error table (21 errors).

**Coverage (self-reported PASS):** all 10 entities + 55 fields; 4 state machines fully expressed; 6 calculations (+ no_show_policy folded into prose: 120-min grace, 3-strike); 21 priority-ordered validations; OCC vehicle-hold rule → ERR_STALE_VERSION (412); 21 errors; 3 roles. Field/Rule/Path-purity hard-contract checks all PASS.

## Steps 5 & 6: Unit tests + Implementation (concurrent) — 2026-06-04T18:41:54.000Z

Launched concurrently in a single message (physical isolation: impl-gen cannot read test_suite/).

**Step 5 (unit tests) result:** `test_helpers/` (9 files) + `test_suite/` (conftest + 6 domain files), **66 tests total**.
- Queue A (Difficulty): 36 tests — all 18 instances × 2 tests each.
- Queue B (Corner): 30 tests — all 30 non-stub instances ≥1.
- Skipped: 0 instances (all passed PRD-first two-condition filter).
- One PRD-first relaxation (not a skip): `pickup_class_mismatch_beats_grace_window_expired` — PRD §3.5 lists grace-window check before class-match check so winner not uniquely-derivable; primary test relaxed to `validate_error_is_one_of([ERR_CLASS_MISMATCH, ERR_GRACE_WINDOW_EXPIRED])`, second variant isolates within-grace → uniquely `ERR_CLASS_MISMATCH`.
- All 66 tests collect cleanly; every test carries exactly one resolving `Design:` tag; no skip/xfail markers.

**Step 6 (implementation) result:** Python+Flask impl in `workspace/implementation/` (27 files).
- `start.sh`: reads `$PORT` (default 10000), binds 0.0.0.0, foreground, `pip install` guarded behind `python3 -c "import flask"` sentinel so per-test reboots don't reinstall.
- **44 endpoints** implemented (every PRD §4 / scaffold §1.5 row incl. reverse-reachability GETs + two `/_` test-driving endpoints).
- Pure in-memory module-level dicts keyed by UUID in `db.py`; no SQLite/disk/JSON. `available_count`/`total_count` recomputed live (denormalized reconciliation); `points_balance`/`lifetime_points`/`no_show_strikes` derived from history with override hooks. Clock overridable via `/_clock/set_current_utc`. Decimal+ROUND_HALF_UP only for loyalty discount; else integer-cent. Nothing seeded; `db.reset()` at boot defensive only.
- Boot verified clean from fresh process + simulated per-test restarts (0 entities after each boot). ~80 end-to-end assertions passing.
- Impl-gen note: could not reproduce the worklog's pinned quote=69700 without exact test inputs, but independent quote checks matched the formula.

## Step 7: Run tests + iterate (long-lived fix subagent) — 2026-06-04T18:41:54.000Z

Spawned the long-lived diagnostic subagent; it owns the run→diagnose→fix→rerun loop (8-round parallel sweep per iteration) until all 8 rounds pass.

**Iterations run:** 2 (initial diagnostic sweep + verification sweep).

**Tests deleted:** None. All four failures were test-side bugs in `test_suite/`, fixed to be more faithful to the PRD rather than deleted, since PRD §3.5/§3.7 verbatim-cover and uniquely determine the settlement arithmetic.

**Fixes applied to test_suite/** (the implementation was PRD-faithful in all four cases):

1. `test_02_lifecycle_and_cascades.py` — `test_confirmed_reservation_pickup_branch_drives_on_rent`: added the missing `get_reservation` to the `from test_helpers import (...)` block. The test called `get_reservation(...)` (raising `NameError`) but never imported it; the helper exists and is exported via `fixtures.py`. Pure import bug; the PRD §3.5 assertion was faithful.

2. `test_01_quote_and_settlement.py` — `test_loyalty_accrual_floor_before_multiply_order_pinned`: corrected expected `final_total_cents` from `20500` to `19750` and accrual `delta_points` from `410` to `394`. The test's expected total omitted the SILVER `LOYALTY_DISCOUNT` line (−750), which PRD §3.7 explicitly includes in the sum-of-ledger-lines final total. final = 15000 base + 2500 overage + 3000 fuel − 750 discount = 19750; accrual = floor(19750/100)×2 = 394.

3. `test_01_quote_and_settlement.py` — `test_mileage_overage_zero_at_allowance_boundary`: replaced the `find_ledger_entries(...) == []` (line-absence) assertion with an amount-zero check on any MILEAGE_OVERAGE line. PRD §3.7 uniquely fixes the overage *amount* to zero at the boundary but does not uniquely determine whether a zero-amount line is emitted or suppressed (fuel alone carries "applies only when" language; mileage does not), so the line-presence assertion was not uniquely derivable (STEP 1c partial-coverage split). The PRD-derivable amount-is-zero assertion is retained.

4. `test_02_lifecycle_and_cascades.py` — `test_writeoff_runs_full_damage_settlement`: corrected expected `final_total_cents` from `265000` to `269500`. The setup uses `ldw_selected=True`, so PRD §3.5/§3.7 require an ADDONS line of 3 days × `ldw_per_day_cents`(1500) = 4500, which the test's expected total omitted. final = 15000 base + 4500 addons + 250000 damage = 269500.

**Fixes applied to implementation/:** None. The settlement logic in `services/settlement.py` and `services/calc.py` correctly implements PRD §3.7 (LOYALTY_DISCOUNT as a negative ledger line, ADDONS from selected waivers, unconditional usage-line emission).

**Final sweep confirmation:** All 8 parallel rounds passed 66/66 (failed=0, errors=0). No flakiness observed across rounds. Orchestrator re-verified: results.{1..8}.json all passed=66 total=66.

## Step 8: Finalize PRD — 2026-06-04T18:41:54.000Z

Step 7 had 4 `test_suite/` fixes (non-zero) → skip condition NOT met → Step 8 runs. Step 7 diff inlined to subagent as focus list.

Produced `workspace/PRD_FINALIZED.md` (271 lines; +1 sentence inserted into §3.7, ~+0.4% chars, line count unchanged).

**Changes (1):**
- **§3.7 — insert** — pinned that the three usage-driven ledger lines (`MILEAGE_OVERAGE`, `FUEL`, `DAMAGE`) are each emitted exactly once per final settlement, unconditionally, including a zero-amount line when the computed amount is zero (rather than suppressed) — `services/settlement.py:58,62,69`.

**Items confirmed pure fixture bugs (no PRD edit):**
- Item 1 (missing `get_reservation` import): §3.5 pickup→ON_RENT already determined. No silence.
- Item 2 (loyalty-accrual test total omitted SILVER LOYALTY_DISCOUNT line): §3.7 already defines `final_total_cents` as signed sum of all ledger lines; §3.9 already pins floor-before-multiply. No silence.
- Item 4 (write-off test total omitted ADDONS line for `ldw_selected=True`): §3.5 already mandates ADDONS provisional line = `rental_days × ldw_per_day_cents`; §3.7/§3.8 keep provisional lines through write-off settlement. No silence.

NO-NEW-MISMATCH check: edit widened from mileage-only to all three usage lines after enumerating `emit_final_usage` (both close + write-off call paths) and the `INCIDENT_REVERSAL`/void path; clarified "applies only when" governs charge amount, not line emission.

## Step 9: Complete PRD — 2026-06-04T18:41:54.000Z

Full PRD-vs-implementation scan; input = PRD_FINALIZED.md (exists). Always runs.

Produced `workspace/PRD_COMPLETED.md` (271 lines; +1236 chars; all in-paragraph). ambiguity-pins = 1, mismatch-revisions = 2.

**Changes (3):**
- **§2.7 Validation Ordering — revise — mismatch** — Gate 2 was "role authorization including member ownership" (before existence), but impl enforces ownership *after* resource load. Pinned: role-level auth is gate 2, member ownership checked after existence resolution → a `Member` hitting a non-existent member/reservation path id gets `ERR_NOT_FOUND`, not `ERR_FORBIDDEN`; exception is reservation creation (body `member_id` checked before lookups). — `routes/members.py:55-103` + `routes/reservations.py:50-232`
- **§3.5 Pickup — revise — mismatch** — Prose listed usability check (`ERR_NO_AVAILABILITY`) before class/location match (`ERR_CLASS_MISMATCH`); impl checks class/location first, usability branch only tests `status == AVAILABLE`. Reordered prose. — `routes/rental_agreements.py:44-58`
- **§3.8 Write-off — insert — ambiguity** — PRD pinned `ERR_ODOMETER_ROLLBACK` guard only on close (§3.7), silent on write-off; impl's `write_off_agreement` omits that guard (accepts `odometer_in < odometer_out`). Pinned that write-off does not impose rollback guard, noted `odometer_in ≥ 0` / `fuel_in_eighths` 0–8 bounds it does enforce. — `routes/rental_agreements.py:232-259`

## Pipeline complete — 2026-06-04T18:41:54.000Z

All 9 steps executed end-to-end. Final 8-round parallel stability sweep: **all 8 rounds 66/66 passing** (failed=0, errors=0). Deliverables present: SCAFFOLD.yaml + 2 design files, worklog.md, test_helpers/, test_suite/ (66 tests), workspace/{INSTRUCTION.md, PRD.md, PRD_FINALIZED.md, PRD_COMPLETED.md, implementation/ + results.{1..8}.json}.
