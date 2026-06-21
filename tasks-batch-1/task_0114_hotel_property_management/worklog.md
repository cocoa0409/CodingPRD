# Worklog — task_0114_hotel_property_management

Scenario: Hotel Property Management System (PMS): reservation/room block, rate plan (BAR/corporate/package), availability/overbooking, room assignment/upgrade, folio/incidentals, night audit, group cutoff, housekeeping status, no-show policy

Difficulty: Expert (10–15 entities, 20–32 endpoints, 18–30 error codes, 3+ calculation variants, 4+ state machines)

## Step 1: Create task directory — 2026-06-03T02:31:32.000Z

Pre-assigned directory `tasks/task_0114_hotel_property_management/` used verbatim (no auto-increment scan). Created `workspace/` subdirectory. INSTRUCTION.md confirmed present at project root.

## Step 2: Generate scaffold — 2026-06-03T02:31:32.000Z

All pinned numeric literals verify against the formulas.

One last correctness check on the no_show cascade instance (§1.8): the no-show reservation is 1 night (07-10..07-11), FULL_STAY policy → charge = nightly × nights = 13500 × 1 = 13500, posted as a NIGHT_AUDIT CHARGE, which feeds `room_charges_cents`. The assert `Folio.room_charges_cents == 13500` is correct. Also the combinatorial #1 instance's distinguishing_aspect prose was a bit convoluted about sum-then-round; the actual pinned literal (33999) and the round-per-night discipline are correctly captured and verified. The instance still validly tests mode (b) rounding-order.

Everything is consistent and lint-clean.

The scaffold for **task_0114_hotel_property_management** is complete. All three required files are written and `scaffold_lint.py` returns **`VERDICT: clean lint`**.

## What was produced

- **SCAFFOLD.yaml** (§1.0–§1.7): flat-topology PMS under `api_prefix: /pms`. Quota-allocation × temporal-windowing archetype; layers = optimistic_concurrency, cascading_side_effects, dual_variant_calculation, rate_threshold_triggers; peer-role RBAC (RevenueManager, FrontDeskAgent, NightAuditor, Guest[entity-backed]).
- **SCAFFOLD_DIFFICULTY_DESIGN.yaml** (§1.8): 9 rule_ids × 2 = **18 instances**, each with an executable empty-DB setup chain.
- **SCAFFOLD_CORNER_DESIGN.yaml** (§1.9): **38 instances** (32 active test recipes + 6 `excluded_because` stubs), walking all 9 claim-guide sections.

## Expert-band audit (per §0.4)

| Dial | Value | Expert band | In band |
|---|---|---|---|
| Entities | **12** | 10–15 | ✅ |
| Endpoints | **48** | 20–32 | ⚠️ over — FK-reverse-reachability forced (known pattern; lint-clean → accepted, not re-run) |
| Error codes | **26** | 18–30 | ✅ |
| Calculation variants | **6 variant entries across 4 dual/multi-variant calcs** | 3+ | ✅ |
| State machines | **6** (Reservation, Room cyclic, GroupBlock, Folio revert-loop, NightAuditRun, CorporateAccount) | 4+ | ✅ |

Endpoint overage (48) is the structural consequence of honoring the Expert 10–15 entity mandate together with the FK lint (one single-resource GET + one filtered-list GET per FK-carrying entity). Lint-clean across all 391 §1.8+§1.9 calls. Accepted per orchestrator memory guidance.

## Step 3: Copy shared files — 2026-06-03T02:31:32.000Z

Copied `INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-03T02:31:32.000Z

PRD generated at `workspace/PRD.md` — **282 lines**.

Sections: §1 Introduction; §2 Global Specifications (2.1 RBAC all four roles incl. Guest entity-backed; 2.2 Response Structure; 2.3 Pagination; 2.4 Common Properties & Versioning incl. availability read-model common_fields:false exception; 2.5 Property Scope / FK Resolution / List Filtering; 2.6 OCC; 2.7 Night-Audit Posture Lock; 2.8 Precision; 2.9 Cross-Entity Cascades; 2.10 Uniqueness); §3 Business Logic (9 subsections); §4 Endpoint Definitions (all 48 endpoints); §5 Error Code Catalogue (all 26 error IDs).

Hard Contracts — all PASS: field coverage 79/79; rule coverage (2 OCC concurrency_rules + 6 state machines + dual-variant calcs + validations priority 1–13); path-purity (0 path tokens in §3); all 26 error IDs catalogued.

Confirmation: difficulty/corner design files NOT read; no sibling task read. Generated purely from SCAFFOLD.yaml + doc-generator spec.

## Step 5: Generate unit tests — 2026-06-03T02:31:32.000Z

Generated test infrastructure. **test_helpers/** (9 files): types.py (11 lifecycle entity TypedDicts + append-only AvailabilityCell w/ only id/created_at, 13 status enums, UserRole), api_client.py (~45 methods, one per endpoint), api_errors.py (26 error IDs + HTTP-status map), assertions.py, factories.py, constants.py, test_users.py (opaque RM/FDA/NA constants + make_guest_headers for entity_backed Guest), fixtures.py (5-tier composite setup), __init__.py barrel.

**test_suite/**: conftest.py + 5 domain test files (test_01–test_05), **68 tests total**.

Coverage: Queue A (Difficulty) **36 tests** — all 18 instances × 2; Queue B (Corner) **32 tests** — all 32 non-stub instances × 1. 6 `excluded_because` stubs NOT translated (all cross-refs resolve to real instances).

Instances SKIPPED for PRD-first failure: **None**. One corner instance (`audit_complete_with_open_departing_balance_returns_blocked`) had a self-inconsistent recipe (departure 07-02 vs business_date 07-01); rebuilt a PRD-faithful setup (arrival 06-30 / departure 07-01 / checked-in on business_date 07-01) that uniquely derives ERR_AUDIT_BLOCKED_OPEN_BALANCE, keeping the assertion intact.

Verification: all 68 tests collect under pytest; all modules import under runner venv; 0 untagged tests; 0 skip/xfail; all 87 PRD citation segments survive literal grep of PRD.md.

## Step 6: Generate implementation — 2026-06-03T02:31:32.000Z

Generated Python + Flask implementation in `workspace/implementation/` (12 files): start.sh (foreground launcher, executable), requirements.txt (flask==3.0.3), app.py, db.py (in-memory dict store), errors.py (26-entry error_id→HTTP map), response.py (meta/response_type/data envelope, req_ id, ISO-8601 UTC 3-digit), middleware.py (X-User-ID/X-User-Role auth + role checks), helpers.py, serialize.py, calc.py (nightly rate PCT round-half-up per night then multiply; forward vs chronological room charge; no-show; folio balance; block pickup/wash; availability/overbooking; corporate outstanding), routes/{config,group_blocks,reservations,folios,audit}.py.

Endpoints: all **48** from PRD §4 (distinct (method,path) set matches table exactly).

Boot contract: start.sh reads $PORT (default 10000), binds 0.0.0.0, `exec python3 app.py` foreground, pip install guarded behind `if ! python3 -c "import flask"` (no per-test reinstall). Storage in-memory module-level dicts; no SQLite/JSON/tmp. No seeded data (all 10 list collections return total_count=0 on fresh boot). Targets Python 3.9 syntax.

Self-verified end-to-end against real `bash start.sh`: full lifecycle, corporate credit gate, OCC stale-version, posture lock, night-audit no-show sweep, dual-variant pricing divergence (forward 90000 vs chronological 40000), PCT round-half-up, availability overbooking boundary, validation ordering, Guest ownership scoping. One bug fixed during self-verify: upgrade endpoint's target_room_type_id now resolves directly against db.room_types (ERR_REFERENCE_NOT_FOUND on unknown).

## Step 7: Test + fix loop — 2026-06-03T02:31:32.000Z

All tests pass across the full 8-round parallel sweep. Final summary below.

**Iterations run:** 2 sweeps (initial diagnostic + verification). One fix batch resolved all 4 deterministic failures; the verification sweep is clean 8/8 (68/68 each round). There was no flakiness — all 4 failures were deterministic across all 8 rounds.

**Tests deleted:** None. All 4 failures were test bugs fixable in-place toward greater PRD fidelity (none were PRD-silent or non-uniquely-derivable).

**Fixes applied to test_suite/ (STEP 2 — test artifact made more faithful to PRD):**

1. `test_04_availability_boundaries_and_invariants.py` — added the missing module-level `_folio(hotel_id, res_id)` wrapper (delegating to the imported `get_folio_for_reservation`). Two tests (`test_void_incidental_restores_folio_balance_to_zero`, `test_void_leaves_surviving_line_in_folio_balance`) called `_folio(...)` but, unlike test_02/test_03, this file never defined it → `NameError`. Pure test-harness bug.

2. `test_04_availability_boundaries_and_invariants.py::test_overbooking_allowance_raises_sellable_count` — the setup passed `overbooking_allowance_pct=0.50`, which the PRD-faithful implementation correctly rejects. PRD §2 (line 118) states verbatim: *"The allowance is a fraction between 0.0 and 0.25 inclusive."* Reworked the fixture to inv=4 / pct=0.25 (the PRD maximum) → `floor(4×1.25)=5` sellable > 4 physical, still proving the allowance raises sellable above physical capacity (sells a 5th reservation; asserts `sellable_count==5`, `sold_count==5`). The PRD-required 0.25 validation cap was preserved, not weakened.

3. `test_01_rate_and_folio_calculations.py::test_chronological_accrual_diverges_from_forward_after_midstay_upgrade` — the assertion `projected_charges_cents == 34000` contradicted PRD §3.5 (line 158): *"When the upgrade is not complimentary, the folio's forward projection is recomputed at the higher rate using the forward room-charge calculation of §3.6."* A paid (non-comp) SUITE upgrade repins the forward projection to SUITE nightly 25500 × 2 = **51000**. The implementation (`routes/reservations.py:275-278`, `calc.room_charge_forward`) computes this correctly. Updated the expected value to 51000 and the docstring to cite §3.5; the core divergence assertion (`projected_charges_cents != room_charges_cents`, i.e. 51000 ≠ 42500) remains intact and meaningful. The KING-pinned 34000 forward projection is already covered separately by `test_forward_projection_pinned_at_confirm_king_only`.

**Fixes applied to test_helpers/:** None.

**Fixes applied to implementation/:** None — the implementation was PRD-faithful in all three substantive cases (overbooking cap 0.0..0.25, paid-upgrade projection recompute). No PRD-required check was weakened.

**Note on round-4 anomaly:** the first verification sweep wrote only 7 of 8 results files (round 4's file was absent with no in-file failure). This was a transient port-acquisition/write hiccup under 8× concurrent load, not a test failure — confirmed by an immediate clean re-run where all 8 files wrote and every round passed 68/68.

Final state verified by orchestrator: results.{1..8}.json all `passed=68 total=68`.

## Step 8: Finalize PRD — 2026-06-03T02:31:32.000Z

`PRD_FINALIZED.md` produced as a byte-for-byte copy of `PRD.md` with **zero edits**. PRD.md = 282 lines, PRD_FINALIZED.md = 282 lines (0% delta).

Changes: None. All three Step 7 fixes were test-artifact corrections where the PRD already uniquely determines the behavior and the implementation matches that prose exactly — no PRD silence, no PRD/impl mismatch to pin.

Per-subject NO-NEW-MISMATCH verification:
1. `_folio` wrapper — pure test-harness construct, no impl behavior choice → no edit.
2. Overbooking allowance cap 0.0..0.25 — impl paths config.py:38-50 (validation/default 0.0), calc.py:142-154 (sellable_count), serialize.py:17 — all consistent with PRD §2 line 118 + §3.3 line 140. Test fixture had used out-of-range 0.50 → no edit.
3. Paid (non-comp) upgrade forward-projection recompute — impl paths reservations.py:121,185,198,275-278, calc.py:75, serialize.py:149 — all consistent with PRD §3.5 line 158. Test had asserted stale KING 34000 vs recomputed SUITE 51000 → no edit.

Outcome matches the prediction that PRD_FINALIZED.md == PRD.md with zero edits.

## Step 9: Complete PRD — 2026-06-03T02:31:32.000Z

Source: PRD_FINALIZED.md (existed) — 282 lines / 47,579 chars. Result: PRD_COMPLETED.md — 282 lines / 49,854 chars (+2,275 chars; line count unchanged, all in-paragraph). **8 changes: 5 ambiguity-pins, 3 mismatch-revisions.** No new sections.

Per-change log:
- §3.1 RatePlan — insert — ambiguity — pinned `adjustment_value` as signed int (percentage-points under PCT, cents under FLAT) — calc.py:62-66, routes/config.py:256.
- §3.3 reservation create — revise — mismatch — body FKs resolve before Guest self-booking auth, so non-existent guest_id → ERR_REFERENCE_NOT_FOUND (422) not ERR_FORBIDDEN (403) — routes/reservations.py:41-48.
- §3.3 availability read — insert — ambiguity — pinned required-param/malformed-date → ERR_INVALID_REQUEST; unresolved room_type_id/hotel_id → ERR_REFERENCE_NOT_FOUND; half-open [start,end) range; array envelope sorted by stay_date asc w/ limit/offset; hotel_id defaults to room type's own — routes/audit.py:232-282.
- §3.5 housekeeping — insert — ambiguity — housekeeping expected_room_version mismatch → ERR_STALE_ROOM_VERSION (412), checked after transition validity — routes/config.py:206-226.
- §3.5 out-of-order toggle — revise — mismatch — OOO toggle runs expected_room_version guard BEFORE assignability check (reverse of §3.9 global order) — routes/config.py:206-209.
- §3.5 upgrade — insert — ambiguity — target_room_type_id resolved as body FK (unknown → ERR_REFERENCE_NOT_FOUND 422); non-boolean comp → ERR_INVALID_REQUEST — routes/reservations.py:256-261.
- §3.8 NightAuditRun — insert — ambiguity — epoch null and three count fields 0 until COMPLETED (abort leaves null/0) — routes/audit.py:63-71,195-199,222.
- §3.8 open audit — insert — ambiguity — ERR_AUDIT_ALREADY_RUNNING evaluated before expected_hotel_version guard, masking ERR_STALE_VERSION when both apply — routes/audit.py:56-61.

Left unchanged (already PRD-pinned): folio money fields, per-night PCT rounding, overbooking floor, no-show vs room-charge type sourcing, upgrade tier rule (strict `<`), path-based guest-ownership ERR_NOT_FOUND on unknown {id}.

---

## PIPELINE COMPLETE — 2026-06-03T02:31:32.000Z

Final verification: results.{1..8}.json all `passed=68 total=68` (8/8 rounds green). Artifacts present: SCAFFOLD.yaml, SCAFFOLD_DIFFICULTY_DESIGN.yaml, SCAFFOLD_CORNER_DESIGN.yaml, test_helpers/, test_suite/ (68 tests), workspace/{INSTRUCTION.md, PRD.md, PRD_FINALIZED.md, PRD_COMPLETED.md, implementation/}.
