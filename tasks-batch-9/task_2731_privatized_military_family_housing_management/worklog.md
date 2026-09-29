# Worklog — task_2731_privatized_military_family_housing_management

## Step 1: Create task directory — 2026-09-04T13:02:49.653Z

Created pre-assigned task directory `/home/ubuntu/github/CodingPRD/tasks/task_2731_privatized_military_family_housing_management` and its `workspace/` subdirectory. Index 2731 was fixed by the scenario number (no auto-allocation scan, per orchestration instructions — other pipelines run concurrently on this host).

## Step 2: Generate Scaffold — 2026-09-04T16:01:30.000Z

All three scaffold artifacts are complete and the lint is clean.

## Files

| Path | Lines |
|---|---|
| `SCAFFOLD.yaml` | 2461 |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 3223 |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 6334 |

Top-level keys verified: `SCAFFOLD.yaml` has 13 keys and contains **neither** `scaffold_difficulty_design` nor `scaffold_corner_design`; the other two files each have exactly one top-level key (`scaffold_difficulty_design`, `scaffold_corner_design`).

## SCAFFOLD.yaml counts (§1.0–§1.7)
- **14 entities** (Installation, BahRate, HousingUnit, ServiceMember, Dependent, WaitlistApplication, Lease, MoveInInspection, WorkOrder, HazardCase, DisplacementLodging, DisputeCase, AllotmentTransaction, ReinvestmentAccount); topology flat
- **9 state-machine dimensions across 8 entities** (Lease carries two independent dimensions: `occupancy_status` x `allotment_status`); shapes include cyclic (WorkOrder, WaitlistApplication, DisputeCase with a 3-round cap) and a branching fork-join (HazardCase)
- **64 endpoints** (41 writes / 23 reads), **46 error codes**, **46-rung single validation ladder**, **18 calculations** (2 dual-variant families + 2 compensating invariants), **3 OCC concurrency rules**, **6 roles** with `role_model: segregation_of_duties`, `consistency_model: immediate`, `difficulty_level: expert_plus`

## SCAFFOLD_DIFFICULTY_DESIGN.yaml (§1.8)
**9 difficulty rules / 25 instances.**

## SCAFFOLD_CORNER_DESIGN.yaml (§1.9)
**9 sections / 86 instances = 63 with full `test_recipe` + 23 `excluded_because` stubs**, all stubs citing a §1.8 instance that exists by exact name (verified programmatically), and all 86 names unique across the union of both design files (zero overlap with the 25 difficulty names).

| Section | Instances (real + stubs) |
|---|---|
| entities | 11 (11 + 0) |
| state_machines | 19 (11 + 8) |
| calculations | 13 (7 + 6) |
| validations | 16 (14 + 2) |
| endpoints | 4 (3 + 1) |
| errors | 9 (6 + 3) |
| rbac | 4 (4 + 0) |
| cross_cutting_complexity_layers | 9 (6 + 3) |
| consistency_model | 1 (1 + 0) |

## Lint verdict (verbatim)

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           tasks/task_2731_privatized_military_family_housing_management/SCAFFOLD.yaml
  Difficulty design:  tasks/task_2731_privatized_military_family_housing_management/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      tasks/task_2731_privatized_military_family_housing_management/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    64
  §1.1 entities declared:     14
  §1.8 instances scanned:     25
  §1.9 instances scanned:     63
  Calls scanned (§1.8+§1.9):  1747

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## Notes worth relaying
- Two lint-driven corrections in this final pass: pagination captures had to stop using `$.data.total_count` / `$.data.has_more` on list endpoints (the linter requires `$.data[N].field` for `Entity[]` outputs), so `total_count` / `has_more` are now asserted in prose while row-indexed captures remain; and the affected assert lines were reworded to match.
- Forbidden concurrency vocabulary swept from both design files: two incidental uses of "simultaneously" (non-race meaning) were reworded; grep for `simultaneous|concurrently|race|at the same time|in parallel` now returns 0 hits in both files.
- The hard constraint was honoured: no sibling `tasks/task_*/` directory was listed, globbed, grepped, or read at any point. Everything came from the scenario text, this task's own SCAFFOLD.yaml, and the scaffold-generator skill (`SKILL.md`, `references/claim-extraction-guide.md`, `scaffold_lint.py`).
- `worklog.md` and `workspace/` already existed in the task directory from an earlier step; I did not touch them.

## Step 3: Copy shared files — 2026-09-04T16:02:44.663Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` to `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-04T16:21:00.000Z

PRD complete and verified.

**Output:** `workspace/PRD.md` — 436 lines, 124,381 bytes, written in 9 sequential chunks (1 `Write` + 8 `cat >>` heredocs) so nothing was truncated.

**Observed tail (last lines of the file):** the §5 error table running from `` `ERR_STALE_APPLICATION_VERSION` | 412 `` down to the final row `` | `ERR_REINVESTMENT_BALANCE_INSUFFICIENT` | 422 | ``. The document ends on a completed final section (§5's 46th and last table row), not mid-sentence, with no audit footer.

**Section list:**
- §1 Introduction
- §2 Global Specifications & System-Wide Principles — 2.1 User and Role-Based Access Control · 2.2 API Response Structure · 2.3 Pagination · 2.4 Resource Identity, Timestamps, and the Logical Clock · 2.5 The Validation Ladder · 2.6 Optimistic Concurrency on Version-Guarded Writes · 2.7 Money, Rounding, and the Append-Only Allotment Ledger · 2.8 Inventory Conservation and Cascade Discipline · 2.9 Segregation of Duties · 2.10 Sub-Collection Reads and Left-to-Right Path Resolution
- §3 Business Logic & Workflows — 3.1 Standing Up a Housing Project · 3.2 Sponsors, Dependents, and the Orders of Record · 3.3 Joining the Waitlist · 3.4 The Offer Run, Acceptance, and Decline · 3.5 Writing the Lease and Setting the Rent · 3.6 Move-In · 3.7 Maintenance · 3.8 Environmental Hazards · 3.9 Collection, Disputes, Termination, and Project Performance
- §4 Endpoint Definitions (4 columns, 64 rows)
- §5 Error Code Catalogue (2 columns, 46 rows)

**Contract 1 — Field-Name Coverage: PASS.** 150 distinct entity field names + 96 distinct endpoint input names (union 164) extracted from SCAFFOLD.yaml; every one appears verbatim inside backticks in PRD.md. Zero missing. Additionally: all 20 entity/type names present, all 101 distinct enum literals from `constraints:` present, all 46 error IDs present, all 64 paths present verbatim in §4.

**Contract 2 — Rule Coverage: PASS.** All 46 validation rungs are stated in §2.5 in ascending priority order with their error ID and HTTP status (all 46 error IDs appear in §2.5 and also outside §5). All 50 declared state transitions across the 9 dimensions are reconstructible — 42 appear as literal `FROM → TO` pairs, and the remaining 8 (`ACTIVE → CLOSED`/`SUSPENDED → CLOSED`, `SCHEDULED`/`DEFICIENCIES_LOGGED → TENANT_ACKNOWLEDGED`, `REMEDIATION_IN_PROGRESS`/`DISPLACEMENT_ACTIVE → CLEARANCE_PENDING`, `ASSESSED → VOIDED`, the `SUBMITTED → SUBMITTED` escalation self-loop) are written as multi-source prose ("from `ACTIVE` or from `SUSPENDED` to `CLOSED`", "available from `ASSESSED`, `REMEDIATION_IN_PROGRESS`, `DISPLACEMENT_ACTIVE` or `CLEARANCE_PENDING`", "a self-loop … preserves the order's `status`"). All 18 calculations are given as ordered prose steps with pinned rounding; every numeric literal in `calculations:` is reproduced (the 6 apparent gaps are decimals expressed as percentages — 0.015 as 1.5 percent, 0.05/0.08/0.10 as five/eight/ten percent — plus a `§1.4` section reference and the "10.00-point divergence" written as "ten full points apart"). All 3 OCC rules and both dual-variant calculations (with the 90.00 vs 100.00 occupancy divergence and the 218150/7172/10-night → 71720 lodging example) are worked out in prose.

**Contract 3 — §3 Path Purity: PASS.** Programmatic scan of §3 (73,494 chars): 0 backtick spans containing `/`, 0 backtick spans containing an HTTP method, 0 raw `/path` tokens anywhere, and 0 occurrences of the bare words GET/POST/PUT/PATCH/DELETE. §2 is equally clean; paths and methods appear only in §4's table.

**Other checks:** §2.2 is byte-identical to `section-2.2-response-structure.md`. §4 rows are uniformly 4 columns, §5 rows uniformly 2. Neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened or grepped, and no sibling task directory was read.

**Three scaffold ambiguities resolved without inventing codes:** the Bill of Rights version mismatch (no scaffold `error_id`) mapped to rung 4's `ERR_INVALID_REQUEST`; `child_under_six_present` documented as a required input whose stored value reflects the dependents on record; and `settlement_charges_cents` defined as the sum of the settlement rows the termination request posts.

**Orchestrator truncation check (independent):** `wc -l` = 436; `tail -12` ends at `| ERR_REINVESTMENT_BALANCE_INSUFFICIENT | 422 |`, a complete table row closing §5. `grep -n '^#'` shows all 5 top-level sections and all 10 §2 subsections present. Not truncated — no regeneration needed.

## Step 5: Generate Unit Tests — 2026-09-04T18:35:00.000Z

Suite complete. Both output directories are at the task root; `ls -d .../workspace/test_*` returns nothing.

## Files written (all under the task root)

**`test_helpers/`** (Stage 1, 3121 lines): `__init__.py` 40, `types.py` 491, `api_errors.py` 107, `test_users.py` 95, `api_client.py` 366 (holds `canonical_instant()`, so every instant comparison is precision-insensitive), `constants.py` 160, `factories.py` 341, `assertions.py` 400, `fixtures.py` 1121.

**`test_suite/`** (Stage 2, 7105 lines, 135 tests): `conftest.py` 67; `test_01` 243/6, `test_02` 178/6, `test_03` 454/11, `test_04` 316/9, `test_05` 492/12, `test_06` 471/13, `test_07` 226/6, `test_08` 444/9 (queue A); `test_09` 590/11, `test_10` 331/5, `test_11` 416/6, `test_12` 564/7, `test_13` 427/8, `test_14` 425/6, `test_15` 647/10, `test_16` 814/10 (queue B).

## Coverage — 88/88 design instances, zero skips

- **Queue A (§1.8): 25/25**, 72 tests, min 2 / max 4 tests per instance.
- **Queue B (§1.9): 63/63 non-stub**, one test each — entities 11, state_machines 11, calculations 7, validations 14, endpoints 3, errors 6, rbac 4, cross_cutting_complexity_layers 6, consistency_model 1. The four `[STUB]`/`excluded_because` corner entries were correctly not translated.
- Machine-verified: 135 tests / 135 `Design:` tags, one tag each, every tag resolves to a real instance name **and** the right section; no untagged, dual-tagged or dangling tags; no occurrence of the word "scaffold"; all files `py_compile` clean; `__pycache__` removed.

## Design-vs-PRD anomalies I corrected (asserted only what the PRD derives)

1. Three queue-A instances assert absolute `allotment_balance_cents` (149657/150159/10901) and row counts that omit the settlement `CHARGE` PRD L302 mandates — I asserted the PRD-derived balances (285925 credited / 147169 uncredited).
2. `housing_unit_out_of_range_and_unknown_enum_values_are_invalid_request` omits `accessibility_features: ["ELEVATOR"]` from a payload its own assert needs — added.
3. `a_reported_hazard_case_admits_neither_void_nor_lodging_nor_clearance` expects `displacement_required == null`; PRD L258 initialises it false — asserted `is False`.
4. Two instances address rows with non-UUID literals (`inst_00000000`, `unit_00000000`, …) where rung 4 would legitimately answer 400 — used `NON_EXISTENT_UUID`.
5. `a_closed_ledger_refuses_a_positive_credit...` terminates before `termination_effective_date`, which PRD L298 refuses — advanced the clock to 2026-10-01 and compared the balance captured from the terminate response.
6. `one_boolean_on_the_clearance_call_forks_the_case_two_ways` declares `child_under_six_present false` for a family whose youngest is 4 — that field is simply not asserted.
7. `every_exclusive_operation_refuses_...` asserts `${e_inst}` but its trigger list has no `POST /installations` call — added the manager-refused call.
8. `hazard_severity_grades_each_type_on_its_own_declared_thresholds` needed a substituted no-young-children family to avoid the vulnerability escalation.
9. PRD internal inconsistency: §4's lodging-close row names `actual_return_date` while §3.8, the entity and the factory use `actual_end_date`; tests send `actual_end_date`.

Nothing has been executed against a running server — validation so far is compile + tag/coverage auditing only.

## Step 6: Generate Implementation — 2026-09-04T17:05:00.000Z

Implementation complete. Everything is in `workspace/implementation/`.

## Files (line counts)

| File | Lines |
|---|---|
`app.py` | 96
`db.py` | 207
`errors.py` | 114
`middleware.py` | 356
`response.py` | 57
`requirements.txt` | 1
`start.sh` (0755) | 13
`services/__init__.py` | 0
`services/calc.py` | 361
`services/core.py` | 301
`services/lookup.py` | 179
`routes/__init__.py` | 0
`routes/system.py` | 17
`routes/installations.py` | 172
`routes/units.py` | 107
`routes/members.py` | 126
`routes/waitlist.py` | 186
`routes/leases.py` | 310
`routes/inspections.py` | 151
`routes/work_orders.py` | 221
`routes/hazards.py` | 371
`routes/disputes.py` | 187
`routes/accounts.py` | 155
**total** | **3688**

## Verification

- **Endpoint parity**: programmatic diff of Flask's `url_map` against SCAFFOLD.yaml's endpoint table — all **64/64** spec endpoints present, zero missing. Only extras are `GET /health` (deliberate, for boot probes) and Flask's `/static` route, which I disabled via `static_folder=None`.
- **Error parity**: programmatic diff of `errors.ERROR_STATUS` against the 46-row error catalog — **46/46 codes with exactly matching HTTP statuses**, no extras, no mismatches.
- **Storage**: in-memory `db.Store` only, `COLLECTIONS` re-initialised per process, no seed data, no disk/SQLite/tmp. Logical clock starts at exactly `2026-08-01T00:00:00Z` (asserted in the smoke run: a freshly created installation carried `created_at == "2026-08-01T00:00:00.000Z"`).
- **Smoke tests**: two scripted end-to-end suites (~120 requests) run against fresh processes on ports 21473/21474, **0 failures**. Coverage included the full happy path (installation → BAH rate → unit → member → dependents → application → offer run → accept → lease → inspection → deficiencies → tenant ack → critical-deficiency work order → move-in → allotment run), hazard branch A and branch B (unit → `HAZARD_HOLD`, lease → `SUSPENDED`, `HAZARD_ABATEMENT:` row), lodging authorization + cascade close into the reinvestment account, clearance with segregation-of-duties (403 for the assessor, 200 for a second specialist), void with full abatement reversal, the 3-round dispute loop auto-escalating and the installation decision posting a `REFUND`, expenditure OCC (412) and balance gate (422), metrics run with duplicate/future-period rejection (409), the offer-decline path, work-order escalate/reopen limits, and the termination notice/terminate settlement + reinvestment cascade. Servers were killed by resolved PID from `ss -lptn 'sport = :PORT'`; no pattern kills were used, and both ports are confirmed free.

## Two defects found and fixed during smoke testing

1. `services/core.release_hazard_hold` blocked the **void** path: an unrelated branch-A case sitting in `REMEDIATION_IN_PROGRESS` on the same unit kept the hold, leaving the unit `HAZARD_HOLD` and the lease `SUSPENDED`. The PRD states the other-open-case guard only for the *clearance* pass ("but only when no other hazard case on that unit is in `DISPLACEMENT_ACTIVE`, `REMEDIATION_IN_PROGRESS` or `CLEARANCE_PENDING`") and describes void's unit/lease transitions unconditionally, so the function now takes `force=False` and `routes/hazards.py` void passes `force=True`; lease reinstatement no longer short-circuits when the unit was never held.
2. `_JSONProvider` was added to `app.py` because `calc.occupancy_rate`/`habitability_penalty` return `Decimal`; those two fields are also cast with `float()` at the store site so `occupancy_rate_pct` / `habitability_penalty_pct` serialise as JSON numbers.

## Notable interpretation choices (all recorded in code comments)

- Rung 20 (terminal) is evaluated before rung 19 per the PRD's own carve-out; hazard clearance on a `REPORTED` case yields rung 26, and lease notice/terminate on `PENDING_MOVE_IN` yields rung 25, so no rung becomes unreachable.
- `POST /leases` checks `ERR_HAZARD_HOLD_ACTIVE` (29) before `ERR_UNIT_NOT_AVAILABLE` (23) so an `ASSIGNED → HAZARD_HOLD` unit reports the hazard hold.
- `POST /dispute-cases` applies rung 3 to both the body `service_member_id` and the lease's sponsor, which enforces the PRD's "must be the lease's own sponsor" without inventing an error code.
- Conditions with no catalogued code (duplicate `unit_code`/`dodid`/`deficiency_code`, `actual_end_date` before `start_date`, terminate before the effective date) map to `ERR_INVALID_REQUEST` or `ERR_INVALID_STATE_TRANSITION` as appropriate.
- `db.bump` is bump-once-per-request (`before_request` → `db.begin_request()`), so a row touched by several cascade hops in one request still advances `version` by exactly 1.

**Orchestrator layout check:** `test_helpers/` (9 files) and `test_suite/` (conftest + 16 test files) are both at the task root; `workspace/test_*` returns nothing; only one `worklog.md` exists (task root).

## Step 7: Run Tests and Iterate — 2026-09-04T18:29:00.000Z

`worklog.md` untouched (mtime still 18:09, before I started). Clean exit.

## Summary

**Iterations run:** 3 (each an 8-round parallel sweep; 131/135 → 134/135 → 135/135)

**Tests deleted:** none. Every failure traced to either a verbatim-PRD-covered rule the implementation got wrong, or a test assertion that contradicted its own cited PRD sentence. No test failed STEP 1a coverage or STEP 1b unique-derivability.

**Fixes applied to `test_suite/`** (no `test_helpers/` changes were needed — the fixtures and factories were sound):

- `test_suite/test_10_lifecycle_transitions.py`, `test_the_expired_application_is_locked_and_refuses_every_offer_verb` — asserted `offered_unit_id` survives a decline that expires the application. PRD §3.4 is verbatim the other way: *"In every case `decline_count` rises by 1, `offered_unit_id` and `offer_expires_at` are cleared"*. The test was internally inconsistent — it already accepted `offer_expires_at is None` from that same sentence while denying it for the sibling field. Changed to `is None`.
- `test_suite/test_11_case_progression_and_escalation.py`, `OFFER_EXPIRES_AT` — pinned `2026-08-27T00:00:00Z` (48h) where the default `offer_response_hours` of 72 off the `2026-08-25T00:00:00Z` fixture clock gives `2026-08-28T00:00:00Z`. Three other test files (`test_12`, `test_15`, `test_16`) independently pin `2026-08-28` for the identical setup, and `test_02` names `2026-08-27` explicitly as `OFFER_EXPIRY_AT_48H` — a plain typo, not a spec disagreement.

**Fixes applied to `implementation/`:**

- `routes/hazards.py`, `certify_clearance` — checked rung 26 (`ERR_HAZARD_NOT_ASSESSED`) before rung 19 (`ERR_INVALID_STATE_TRANSITION`). PRD §2.5: *"No later rung may pre-empt an earlier one."* Reordered; the rung-26 check is retained below rung 19 rather than deleted.
- `routes/leases.py`, `termination_notice` — same inversion, rung 25 (`ERR_LEASE_NOT_OCCUPIED`) ahead of rung 19. Reordered.
- `routes/leases.py`, `terminate` — the identical inversion in the sibling handler. No test exercised it, but it is the same PRD-ladder violation, so I corrected it symmetrically.
- `routes/waitlist.py`, `recertify` — had no rung-20 terminal-state check at all, so recertifying an `EXPIRED` application succeeded with 200. Rung 20 names `EXPIRED` terminal for a waitlist application and, unlike rung 19, is not scoped to state-machine-driving endpoints. Added the check after the rung-17 version check, which is what makes the test's *"terminal beats stale"* case land.
- `middleware.py`, `DEPLOYMENT_STATUSES` — enum member was `RETURNING`; PRD §3.2 says `RETURNED` (as do `test_helpers/types.py` and `assertions.py`). No test sent the value, so this was latent; fixed as a one-word fidelity correction.

**Note on the ladder fixes:** the three reorderings mean rung 25 is now unreachable for termination-notice/terminate and rung 26 unreachable for clearance. That is the correct consequence of the PRD's "primary target" wording rather than a sign of over-fitting — rung 25 stays live for dispute *opening*, where the lease is only a referenced resource and no rung 19 applies. The implementation already handled that case correctly, and `test_13`'s docstring states the same reading: *"the referenced lease answers 25, the targeted lease 19."*

**Final per-round figures — all 8 rounds 135/135 passed, 0 failed, 0 errors, 0 skipped** (~252s per round, genuinely distinct concurrent runs). No `pytest.mark.skip`/`xfail` anywhere in the suite, no assertions weakened, and no endpoint, field, or seeded data added to the implementation.

**Orchestrator independent verification of the final sweep:** all 8 `workspace/implementation/results.{1..8}.json` exist (~42 KB each, mtime 18:28) and each parses to `passed=135, failed=0, errors=0, skipped=0, total=135`. Sweep artifacts confirmed present — not a claimed-clean-without-evidence exit. Step 8 will run (Step 7 applied 5 implementation fixes, so the skip condition does not hold).

## Step 8: Finalize PRD — 2026-09-04T18:50:00.000Z

Done. One PRD edit was warranted; the other Step 7 items were already uniquely determined by PRD prose (or were pure test bugs).

## Counts
- `PRD.md`: 436 lines / 124,381 bytes
- `PRD_FINALIZED.md`: 436 lines / 124,825 bytes
- Line delta: 0 (0.0%); byte delta: +444 (+0.36%) — a single in-line append to §3.3

## Changes
- **§3.3 (Joining the Waitlist … Recertification)** — insert — appended to the recertification paragraph: recertification drives no state machine, so rung 19 never applies and `status` is never moved; rung 20 *does* apply, so a recertification of a `HOUSED`/`EXPIRED` application is refused `ERR_TERMINAL_STATE_LOCKED` (409) even with a matching `expected_application_version`, while `PENDING`, `OFFERED` and `ACCEPTED` are all recertifiable — `implementation/routes/waitlist.py:111-115`.

## Per-edit pre-edit search log
**Edit 1 — §3.3 recertify rung-20 guard**
- (a) Subject: applicability of the rung-20 terminal-state guard (and non-applicability of rung 19) to `POST /waitlist-applications/{id}/recertify`, plus which application statuses are recertifiable.
- (b) Paths enumerated: `grep -rn "ERR_TERMINAL_STATE_LOCKED"` across all of `implementation/` (16 sites: `routes/hazards.py:146,210,252,366`, `routes/waitlist.py:115,134`, `routes/disputes.py:24`, `routes/work_orders.py:25`, `routes/leases.py:182,228,267`, `routes/inspections.py:30,78,115`, `errors.py:28,79`); read `routes/waitlist.py` in full (`create_application`, `recertify`, `_guard_offer_state`, `accept_offer`, `decline_offer`); read `routes/installations.py:99-149` (offer run — only touches `PENDING` applications, so the OFFERED/ACCEPTED-recertifiable claim cannot collide with it); grepped every other application-status read (`routes/leases.py:43-88` create-lease requires `ACCEPTED` and sets `HOUSED`; `services/core.py:23` pending recount; `services/lookup.py:87-88` `check_application_version`); `middleware.py:44-50` for `APPLICATION_STATUSES`/`DEPLOYMENT_STATUSES`; PRD §2.5 rungs 19/20 and §2.6 recertification prose for consistency.
- (c) Wording adjustments: scoped the sentence to recertification only rather than editing the global rung-20 sentence in §2.5, so the 13 other terminal-guard sites keep their existing (already PRD-determined) semantics; enumerated the recertifiable statuses explicitly (`PENDING`, `OFFERED`, `ACCEPTED`) instead of writing "while `PENDING`" so as not to falsely narrow the impl, which recertifies `OFFERED`/`ACCEPTED` rows too; added "never moves the application's `status`" only after confirming `recertify` writes no status and triggers no recount.

## Items deliberately not patched
- **`routes/hazards.py` `certify_clearance`, `routes/leases.py` `termination_notice`/`terminate` rung reorderings** — §2.5 already says verbatim "No later rung may pre-empt an earlier one", scopes rung 19 to non-terminal primary targets, and §3.8/§3.9 already declare the single valid edges (`CLEARANCE_PENDING`, `OCCUPIED`, `NOTICE_GIVEN`). Behaviour is derivable as-is; I also left the §2.5 rung 25/26 "guards two/three operations" wording verbatim rather than softening it — rung 26 stays live for lodging authorisation (`routes/hazards.py:299-300`) and rung 25 for dispute opening (`routes/disputes.py`), and rewriting it risked a new mismatch.
- **`middleware.py` `DEPLOYMENT_STATUSES` `RETURNING`→`RETURNED`** — PRD §3.2 (line 174) already says `RETURNED`; pure impl-fidelity fix.
- **`test_10` `offered_unit_id` cleared on decline** — PRD §3.4 already states it verbatim; test-only bug.
- **`test_11` `OFFER_EXPIRES_AT`** — PRD pins `offer_response_hours` default 72 (line 158) and `offer_expires_at = clock + offer_response_hours` (line 204); the 48h constant was a test typo.

**Orchestrator verification:** `PRD_FINALIZED.md` exists (436 lines / 124,825 bytes) and `cmp` confirms it differs from `PRD.md`.

## Step 9: Complete PRD — 2026-09-04T19:25:00.000Z

Run as **three sequential module-partitioned passes** over one shared `workspace/PRD_COMPLETED.md` (pass 1 performed the `cp PRD_FINALIZED.md PRD_COMPLETED.md`; passes 2 and 3 were explicitly forbidden from re-copying, which would have destroyed earlier edits). Partition by implementation module so no two passes contend for the same prose:
- Pass 1: `app.py`, `db.py`, `errors.py`, `middleware.py`, `response.py`, `services/lookup.py`, `routes/system.py`, `routes/installations.py`, `routes/units.py`, `routes/members.py`
- Pass 2: `routes/waitlist.py`, `routes/leases.py`, `routes/inspections.py`, `services/core.py`
- Pass 3: `routes/work_orders.py`, `routes/hazards.py`, `routes/disputes.py`, `routes/accounts.py`, `services/calc.py`

### Pass 1 (core + intake) — 21 ambiguity-pins, 6 mismatch-revisions
436 lines / 124,825 bytes → 437 lines / 133,482 bytes.
- §2.1 — insert — ambiguity — empty-string `X-User-ID`/`X-User-Role` counts as absent for rung 1 — `middleware.py:94`
- §2.1 — revise — mismatch — ownership list is exhaustive; not enforced on collection lists, sponsor read, dependent listing, hazard-case/lodging reads — `routes/members.py:54,60`
- §2.2 — revise — ambiguity — `api_request_id` is `req_` + exactly 20 uppercase-alnum chars — `db.py:137`
- §2.2 — revise — mismatch — `api_request_timestamp` comes from real wall time, not the logical clock — `response.py:13`
- §2.2 — insert — ambiguity — `message` text is advisory, not contractual — `errors.py:113`
- §2.2 — insert — ambiguity — transport failures: unrouted path → `ERR_INVALID_REQUEST`/404, bad method → 405, unparseable/non-object body → 400, server fault → `ERR_INTERNAL`/500, trailing slash insignificant — `app.py:63-86,46`
- §2.3 — insert — ambiguity — empty `limit`/`offset` take defaults; whitespace-padded/non-integer rejected — `middleware.py:288-297`
- §2.3 — insert — ambiguity — `created_at` ties broken by insertion sequence; empty filter = omitted; out-of-enum/non-integer filter → 400; boolean filter accepts `true/True/TRUE/1` and `false/False/FALSE/0` — `db.py:189`, `middleware.py:300-336`
- §2.4 — insert — ambiguity — clock setter performs no auth/role check, requires parseable `current_utc`, answers 200 with empty `data` — `routes/system.py:12-17`
- §2.4 — insert — ambiguity — dates exactly 10 chars; datetimes accept `Z` or numeric offset, zone-less read as UTC; `period_month` exactly 7 chars, month 01-12 — `db.py:76-106`
- §2.5 rungs 1-3 — revise — mismatch — rung 2 exempts the clock setter; rung 3 scope narrowed to §2.1 resources, skipped when sponsor reference absent/non-string/unresolvable — `middleware.py:103-134`
- §2.5 rung 4 — insert — ambiguity — JSON `null` == omitted (never clears); strings non-empty after strip; booleans strict, never integers; absent body = `{}`; cross-field bounds are rung-4; undeclared fields ignored — `middleware.py:120-201`
- §2.7 — insert — ambiguity — `occupancy_rate_pct` serialises as a plain JSON number, so 90.00 appears as `90.0` — `app.py:33-39`
- §2.8 — insert — ambiguity — `version` advances once per row per request even on multiple writes; `updated_at` refreshes each write — `db.py:158-170`
- §3.1 — insert — ambiguity — both BAH monetary bounds are rung-4 (before installation resolves); no uniqueness over the rate selector — `routes/installations.py:82-87`
- §3.1 — insert — ambiguity — duplicate `unit_code` → `ERR_INVALID_REQUEST`, after the installation resolves — `routes/units.py:35-37`
- §3.1 — insert — ambiguity — `accessibility_features` must be an array of the three declared codes; duplicates collapsed in first-supplied order — `middleware.py:260-273`
- §3.1 — revise — mismatch — "four operator-visible edges" → five; any of the five statuses passes rung 4 while an undeclared edge (incl. no-op) fails rung 19; `hazard_hold_reason` required at rung 4, cleared on every non-hold target; rung 20 never fires — `routes/units.py:14-20,84-104`
- §3.1 — insert — ambiguity — blocked hold release → `ERR_INVALID_STATE_TRANSITION` (409) — `routes/units.py:93-98`
- §3.2 — insert — ambiguity — duplicate `dodid` → `ERR_INVALID_REQUEST` — `routes/members.py:32-34`
- §3.2 — insert — ambiguity — `null` counts as not supplied so no field can be blanked; sponsor `version` +1 even on an empty recording — `routes/members.py:88-101`
- §3.2 — insert — ambiguity — adding a dependent bumps the sponsor's `version`; dependents carry `updated_at`/`version`, no single-row read — `routes/members.py:124-126`
- §3.4 — insert — ambiguity — installation `version` +1 per run, all seven counters recomputed, no request body, one shared `offer_expires_at` per run — `routes/installations.py:110-149`
- §3.9 — insert — ambiguity — each charged lease `version` +1, skipped leases untouched; duplicate test ignores `source_ref`; no future-period check; installation `version` unchanged — `routes/installations.py:161-172`
- §4 — insert — ambiguity — `GET /health` is unauthenticated and returns bare `{"status": "ok"}` outside the envelope — `app.py:55-57`
- §4 — revise — mismatch — clock-setter authorised-roles cell → "Unauthenticated — no header or role check" — `routes/system.py:13`
- §4 — revise — mismatch — `GET /housing-units` row gained the omitted `unit_type` filter — `routes/units.py:67,76`

Notable non-changes: §5 catalogue matches `errors.py` exactly for all 46 ids/statuses (`ERR_INTERNAL` documented in §2.2 as transport-level rather than added to the catalogue); §2.6's "non-optional" version fields are correct — all three routes require them via `v_int(required=True)`.

### Pass 2 (waitlist / lease / inspection) — 8 ambiguity-pins, 8 mismatch-revisions
437 lines / 133,482 bytes → 437 lines / 140,076 bytes. No `cp`, no whole-file write. No pass-1 wording reverted; nothing conflicted.
- §2.5 rungs 29-31 — revise — mismatch — rung 29 (hazard hold) evaluated **ahead of** rung 23 on lease creation, so a held offered unit answers `ERR_HAZARD_HOLD_ACTIVE`; on move-in it keeps its slot (after 24, before 30) — `routes/leases.py:47-50,192`
- §3.5 — revise — mismatch — six-gate list reordered to impl's actual order (hazard hold before availability); the "ladder order of §2.5" claim qualified — `routes/leases.py:45-60`
- §3.4 — revise — mismatch — `decline_reason` is shape-validated when present but **not persisted** and appears in no response field — `routes/waitlist.py:167`
- §3.5 — insert — mismatch — redetermination drives no state machine, so rungs 19/20 are not evaluated and `occupancy_status` is never inspected: even a `TERMINATED` lease is re-priced on a matching version token — `routes/leases.py:154-170`
- §3.6 — insert — mismatch — the Bill-of-Rights version comparison cannot run at rung 4 (needs lease→unit→installation) and is evaluated **after** the inspection's state gates; plus the explicit `ERR_TERMINAL_STATE_LOCKED`/`ERR_INVALID_STATE_TRANSITION` answers — `routes/inspections.py:113-124`
- §3.6 — revise — mismatch — "requires the unit to be `ASSIGNED`" replaced: `HAZARD_HOLD` is the *only* unit-status gate (`AVAILABLE`/`OFFLINE_MAINTENANCE`/`OCCUPIED` all move in) and answers before the habitability count; "at least one" acknowledged inspection, one clear inspection suffices — `routes/leases.py:181-197`
- §3.9 — revise — mismatch — the unit is driven to `AVAILABLE` from whatever status it held (including `HAZARD_HOLD`) and `hazard_hold_reason` is left standing — `routes/leases.py:306-309`
- §3.9 — revise — mismatch — contribution targets **every** account row for the installation and fiscal year in `created_at` order, silently skipped when none matches (overriding §2.8's default "missing cascade target is a failure"), and skipped entirely when the rounded amount is 0 — `services/core.py:215-221`
- §3.3 — insert — ambiguity — a supplied replacement `pcs_orders_date` overwrites the stored value before recomputation; omission leaves it unchanged — `routes/waitlist.py:119-120`
- §3.5 — insert — ambiguity — when several BAH rate rows match the four-part key the **most recently loaded** wins (`created_at` asc, insertion tie-break) — `services/core.py:85-90`
- §3.6 — insert — ambiguity — `scheduled_date` unconstrained; `TERMINATED` lease → `ERR_TERMINAL_STATE_LOCKED`, other non-`PENDING_MOVE_IN` → `ERR_INVALID_STATE_TRANSITION`; multiple inspections per lease allowed — `routes/inspections.py:29-33`
- §3.6 — insert — ambiguity — `COMPLETED` → terminal lock, `TENANT_ACKNOWLEDGED` → invalid transition; `deficiencies` required, and an empty array still advances `SCHEDULED → DEFICIENCIES_LOGGED` with counters at 0 — `routes/inspections.py:62-80`
- §3.6 — insert — ambiguity — duplicate `deficiency_code` (stored or earlier in the same batch) → `ERR_INVALID_REQUEST` with **nothing appended** — `routes/inspections.py:82-86`
- §3.6 — insert — ambiguity — spawned order carries the inspection's `lease_id`, null `parent_work_order_id`/`assigned_tech_user_id`, generated `description` of the form `Move-in inspection deficiency <code> in <room>`, and can never take the under-six escalation (no `OCCUPIED` lease yet) — `routes/inspections.py:139-143`, `services/core.py:127-146`
- §3.9 — insert — ambiguity — rungs 19/20 answer (not rung 25): `TERMINATED` → terminal lock, `PENDING_MOVE_IN`/`NOTICE_GIVEN` → invalid transition, so `ERR_LEASE_NOT_OCCUPIED` is never observed on notice or termination — `routes/leases.py:227-234,266-273`
- §3.9 — insert — ambiguity — premature closing is `ERR_INVALID_STATE_TRANSITION` (409); the clock date landing exactly on `termination_effective_date` is permitted — `routes/leases.py:275-278`

### Pass 3 (work orders / hazards / disputes / accounts / calc) — 18 ambiguity-pins, 10 mismatch-revisions
437 lines / 140,076 bytes → 437 lines / 146,364 bytes. No `cp`, no whole-file write.
- §3.7 — insert — ambiguity — resident submitter must own the named `lease_id` (`ERR_NOT_RESOURCE_OWNER`); no `lease_id` → no ownership check — `routes/work_orders.py:39`
- §3.7 — insert — ambiguity — `assigned_tech_user_id` recorded verbatim, never checked against any user/role record — `work_orders.py:100`
- §3.7 — revise — mismatch — PRD said "the **assigned** MaintenanceTech"; impl compares no identity, so any tech may start/complete; missing tech on start → `ERR_INVALID_STATE_TRANSITION` — `work_orders.py:113`
- §3.7 — insert — ambiguity — `completion_note` and `reopen_reason` validated but not persisted/echoed — `work_orders.py:129,176`
- §3.7 — insert — ambiguity — resident ownership applies; an order already at level 2 re-escalates (level pinned at 2, `escalated_at` re-stamped, version +1) rather than being refused — `work_orders.py:203,208`
- §3.8 — insert — ambiguity — a case with no `lease_id` always stores `child_under_six_present` false — `routes/hazards.py:106`
- §3.8 — revise — mismatch — the `HAZARD_HOLD` hop fires only from `OCCUPIED`, while lease suspension + abatement are driven by `displacement_required` alone and run even when the unit does not move; non-`ACTIVE` leases untouched — `hazards.py:180`
- §3.8 — insert — ambiguity — `REPORTED` is the *only* refused case status for lodging; a `CLOSED`/`VOIDED` case still accepts a lodging — `hazards.py:299`
- §3.8 — insert — ambiguity — no ordering constraint between `start_date` and `end_date` — `hazards.py:291`
- §3.8 — insert — ambiguity — `actual_end_date` before `start_date` → `ERR_INVALID_REQUEST`, evaluated *after* the state rungs — `hazards.py:369`
- §3.8 — insert — mismatch — state answer precedes SoD; a non-`CLEARANCE_PENDING` case gives `ERR_INVALID_STATE_TRANSITION` (never `ERR_HAZARD_NOT_ASSESSED`) — `hazards.py:209`
- §2.5 rung 26 — revise — mismatch — corrected the pre-existing claim that rung 26 is observable on clearance certification; it is reachable only on lodging authorisation — `hazards.py:213`
- §3.8 — insert — ambiguity — follow-on order's `category` (hazard family) and `habitability_impact` = case's `displacement_required` — `hazards.py:232`
- §3.8 — revise — mismatch — the `SUSPENDED → ACTIVE` lease hop travels with the hold release, so a kept hold (second open case) or a never-held unit leaves the lease suspended — `hazards.py:225`
- §3.8 — insert — ambiguity — resident must own any `lease_id` named on a hazard report — `hazards.py:31`
- §3.8 — insert — ambiguity — the forced 0-night closures move no reinvestment account and no account version — `hazards.py:264`
- §3.8 — revise — ambiguity — one `ARREARS_ADJUSTMENT` per affected lease, same `HAZARD_ABATEMENT:` `source_ref`, `period_month` from the last reversed row, skipped when the sum is 0 — `hazards.py:266`
- §3.9 — revise — ambiguity — sponsor/lease agreement enforced by the ownership rung (no mismatch code); stored value copied from the lease — `routes/disputes.py:57`
- §3.9 — insert — ambiguity — a proposal past the round cap is refused with `ERR_INVALID_STATE_TRANSITION` — `disputes.py:129`
- §3.9 — insert — ambiguity — `REFUND` `period_month` is the logical clock's month; a 0 award posts nothing; lease version +1; same rule on the installation decision — `disputes.py:35`
- §3.9 — revise — mismatch — `MONTH_END_SNAPSHOT` counts the **live** unit status (no status history), not the period's last day; zero units → 0.00 — `services/calc.py:297`
- §3.9 — insert — ambiguity — `habitability_penalty_pct` stored as a decimal fraction (0.15, capped 0.5, zero as `0.0`); multiplier not stored — `calc.py:346`, `accounts.py:146`
- §3.9 — insert — ambiguity — nothing is floored: a negative `net_collected_cents` carries its sign into base fee, incentive fee and contribution — `calc.py:351`, `accounts.py:148`
- §3.9 — insert — ambiguity — a 0-cent expenditure authorisation is accepted and still bumps the account version — `routes/accounts.py:78`
- §4 — revise — mismatch — `POST /work-orders`: `sla_response_due_at`/`sla_resolution_due_at` → `response_due_at`/`completion_due_at` — `services/core.py:159`
- §4 — revise — mismatch — `POST /hazard-cases/{id}/assess`: `severity_grade` → `assessment_severity` — `hazards.py:157`
- §4 — revise — mismatch — `POST /displacement-lodgings/{id}/close`: `actual_return_date` → `actual_end_date` — `hazards.py:362`
- §4 — revise — mismatch — `POST /dispute-cases/{id}/propose-resolution`: `credit_offer_cents` is required (may be 0), not optional — `disputes.py:126`

**Cross-pass conflict resolved:** pass 3 found §2.5 rung 26's claim that it guards clearance certification contradicted by its slice's ordering. The wording was corrected in place (precedence clause added) rather than reverted, and the same fact pinned in §3.8.

### Totals and integrity
**47 ambiguity-pins, 24 mismatch-revisions across the three passes.**

Pass-3 document-integrity check: 5 top-level sections (§1–§5); all 10 §2 subsections; §4 endpoint table exactly **64** method rows (matching 64 `@bp` routes); §5 catalogue exactly **46** `ERR_*` rows; file ends on the complete final table row `| ERR_REINVESTMENT_BALANCE_INSUFFICIENT | 422 |`, not truncated. The only unbalanced-backtick lines (31, 44, 56, 68) are the pre-existing ```json fences, identical in `PRD_FINALIZED.md`.

**Orchestrator independent verification:**
- `PRD.md` 436 lines / 124,381 B · `PRD_FINALIZED.md` 436 lines / 124,825 B · `PRD_COMPLETED.md` 437 lines / **146,364 B**.
- `cmp PRD_FINALIZED.md PRD_COMPLETED.md` → differs (3,596 word-level diff tokens), so the scan demonstrably ran; it is **not** a byte-identical copy.
- `find` confirms zero `.py` files under `workspace/implementation/`, `test_suite/`, or `test_helpers/` are newer than `results.1.json` — Step 9 touched documentation only, so the verified 8/8 × 135/135 sweep from Step 7 still holds for the delivered artifacts.

## Pipeline complete — 2026-09-04T19:26:00.000Z

All nine steps finished. Final artifact set: `SCAFFOLD.yaml` + two design indices, `test_helpers/` (9 files), `test_suite/` (conftest + 16 files, 135 tests), `workspace/{INSTRUCTION.md, PRD.md, PRD_FINALIZED.md, PRD_COMPLETED.md, implementation/}`, and `workspace/implementation/results.{1..8}.json` all recording 135/135.
