# Worklog — task_2722_charity_golf_outing_operations

## Step 1: Create task directory — 2026-09-04T12:02:00.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2722_charity_golf_outing_operations` and its `workspace/` subdirectory. Index 2722 was pre-assigned by the orchestrating prompt (no scan of ./tasks/ performed, to avoid collisions with the ~32 concurrent pipelines on this host).

## Step 2: Generate scaffold — 2026-09-04T14:10:00.000Z

All three scaffold artifacts for task 2722 are complete and lint-clean.

**Files** (all in `/home/ubuntu/github/CodingPRD/tasks/task_2722_charity_golf_outing_operations/`):

| file | lines | bytes |
|---|---|---|
| `SCAFFOLD.yaml` | 2330 | 155143 |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 1828 | 124097 |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 5308 | 375083 |

**Content shape**
- `SCAFFOLD.yaml`: §1.0–§1.7 only — 11 entities, 9 state-machine blocks (parallel dimensions), 10 calculations, 40 validations, 54 endpoints, 62 error codes, 6 roles, 3 §1.2.1 concurrency rules. Top-level keys contain neither `scaffold_difficulty_design` nor `scaffold_corner_design`; the scenario is stored verbatim (including "Generate task harder than expert level!" and "simultaneous-start logistics" — the only occurrence of forbidden concurrency vocabulary anywhere, and it is inside the verbatim scenario).
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml`: single top-level key, 9 hard-reasoning rules x 2 instances = 23 instances.
- `SCAFFOLD_CORNER_DESIGN.yaml`: single top-level key, 95 instances across the nine guide sections — entities 12, state_machines 22, calculations 18, validations 23, endpoints 4, errors 2, rbac 4, cross_cutting_complexity_layers 9, consistency_model 1. 71 carry full `test_recipe` chains; 24 are `excluded_because` stubs, each citing an existing §1.8 instance name.

**Final work this session** (the remaining §1.9 sections): the error-envelope instance across the 422/404/409/402 classes and a six-fault `ERR_INVALID_REQUEST` instance (proving priority 3 outranks `ERR_TEAM_SIZE_INVALID`); the four RBAC instances (`ERR_UNAUTHENTICATED` header defects incl. priority 1 > 2 > 3 ordering, per-role exclusive fences incl. 403-before-404, the `entity_backed:Player` own-row fence, and the sale-recorder vs receipt-issuer segregation of duties); both remaining OCC rules (`ERR_STALE_TEAM_VERSION` on tee-assignment, `ERR_STALE_REGISTRATION_VERSION` on amend-tier, each proving OCC fires ahead of the tee-slot and payment-mismatch checks); the insurance rate-threshold boundary at 499999/500000/900000; six layer stubs; and the `immediate` consistency instance.

**Verification**
- `scaffold_lint.py`: `§1.5 endpoints declared: 54 / §1.1 entities declared: 11 / §1.8 instances scanned: 23 / §1.9 instances scanned: 71 / Calls scanned (§1.8+§1.9): 1337` -> `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.`
- Error coverage: all 62 §1.6 codes are referenced by at least one instance in the two design files (0 uncovered).
- Instance names: 118 total across both files, 0 duplicates; 0 unbound `${var}` in any payload, path, or assert; no stub carries a `test_recipe` and every cited `difficulty_instance` resolves.
- Two lint fixes were needed and applied: an `as_user_id` retrofit on the 22 identity-sensitive calls (segregation-of-duties users `sm-approver`/`sm-verifier`, `ct-seller`/`ct-issuer`, and the Participant `${p1_id}`), and `cart_allowance` -> `cart_allowance_count` on one contract payload.

Orchestrator note: verified post-step that `workspace/` and `worklog.md` survived the scaffold subagent (known failure mode: Step 2 wiping the task dir).

## Step 3: Copy shared files — 2026-09-04T14:10:30.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` to `workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-04T14:26:00.000Z

PRD generation complete.

## Output

`workspace/PRD.md`

- **521 lines, 111,648 bytes**
- Written in 8 chunked appends (no single write exceeded ~30 KB), so no truncation occurred.
- **Last heading: `## 5. Error Code Catalogue`**; the file's final line is the table row `| `ERR_REMITTANCE_AMOUNT_MISMATCH` | 402 |` — a genuine section boundary, no audit footer, no trailing prose.
- Structure: §1 Introduction; §2 with eleven domain-derived subsections (2.1 RBAC, 2.2 verbatim response block, 2.3 Pagination, 2.4 Common Properties and the Logical Clock, 2.5 Amounts/Handicaps/Rounding, 2.6 The Validation Ladder, 2.7 Superseding Writes and Version Guards, 2.8 Cascade Propagation, 2.9 Segregation of Duties, 2.10 Sponsorship Inventory Conservation, 2.11 Parallel Lifecycle Dimensions); §3 with nine narrative subsections (3.1 outing + course contract -> 3.9 reconciliation/net-proceeds/remittance); §4 endpoint table (4 columns, 54 rows); §5 error table (2 columns, 62 rows). Exactly 118 table rows total, and the only code fences are the two JSON blocks inside the fixed §2.2 block (confirmed byte-identical to `section-2.2-response-structure.md`).

## Hard Contract reports

**Contract 1 — Field-Name Coverage: PASS.** Mechanically verified against a 178-name inventory built from `entities[].fields[].name` union all `endpoints[].input`/`query_params`/`path_params` identifiers: 178 required, 0 missing, every one present verbatim inside backticks.

**Contract 2 — Rule Coverage: PASS.** Verified mechanically plus by review:
- All 62 error IDs appear in §1–§3 prose (not only in the §5 table), each attached to its triggering condition.
- All 9 state-machine blocks: every declared state name present; every transition's from->to pair described in proximity (0 gaps); every `action` enum literal (`OPEN_REGISTRATION`...`CANCEL_OUTING`, `SIGN`/`AMEND`/`VOID`, `CHECK_IN`/`RECONFIRM`/`CANCEL`, `WITHDRAW`/`RESTORE`, `COMMIT`/`APPROVE_ARTWORK`/`INSTALL`/`VERIFY`/`WAIVE`/`RELEASE`, `OPEN`/`CLOSE`/`VOID`, `VOID`/`RELIST`, `RECONCILE`/`REOPEN`/`REMIT`) present in §3.
- All 3 `concurrency_rules[]` stated in §2.7 with write operation + `expected_team_version`/`expected_registration_version`/`expected_outing_version` + `ERR_STALE_*_VERSION` + 412, and re-stated at each use site.
- Validation ordering: §2.6 gives the 12-tier ladder plus the five business sub-tiers (safety -> referential -> temporal -> constraint -> fiscal) with each sub-tier's error IDs in priority order, including the pinned `ERR_ASSET_WITHDRAWN` before `ERR_ASSET_CAPACITY_EXCEEDED`.
- All 10 calculations in prose with every constant: SCRAMBLE weights 0.20/0.15/0.10/0.05, BEST_BALL 0.90, STROKE_PLAY 1.00, the 0.25 aggregator and pre-aggregation whole-stroke rounding, sandbag cap 3.0, 7-key ranking, prize shares 0.50/0.30/residual, 1/2/3/6/18 net divisors, 0.60 waiver credit, 0.25 late-cancel fee, admin-fee ladder (0 / 0.05 / 0.035 / 0.02 at the 2000000 and 5000000 boundaries, base = gross revenue, order pinned), token-benefit 1300 cents / 2%, amateur cash cap 75000, insurance threshold 500000, 30/15-minute cart turnaround/prep, 30-minute closed service-window padding.
- Sibling-branch symmetry stated explicitly wherever a transition has multiple origins; `applies_to` scopes, field defaults/types, and cross-entity side effects all covered.

**Contract 3 — §3 Path Purity: PASS.** 359 distinct backtick tokens in §3, 0 violations: none begins with `/`, none is a bare HTTP method, none combines method+path. Endpoints are referred to by state-pair framing (`FIELD_LOCKED -> POSTPONED`), role+action framing, or capability description.

Two things worth flagging to the pipeline: the withheld design files were never opened, and no sibling task directory was read. Also, I resolved five scaffold-internal contradictions deliberately — auth header spelled `X-User-ID` (SKILL.md wins over the validations' `X-User-Id`); tee-assignment check order taken from the validation priority numbers (slot -> cart turnaround -> wave window -> allowance) rather than the endpoint `side_effects` prose; `CANCEL_OUTING` cascade limited to what the state machine declares (`PENDING_PAYMENT`/`WAITLISTED` -> `CANCELLED`) rather than the broader `side_effects` claim; strict tee-time equality asserted for `SHOTGUN` only; and the prize residual paid only to the third eligible team.

Orchestrator truncation check (per known doc-generator failure mode): independently ran `wc -l/-c`, listed all headings, and read the last 600 bytes. File ends on the final `ERR_REMITTANCE_AMOUNT_MISMATCH | 402` table row under `## 5. Error Code Catalogue` — a real section boundary. No regeneration needed.

## Step 5: Generate unit tests — 2026-09-04T16:30:00.000Z

Test generation is complete. Final two files written this session, then all closing audits run.

**New files**
- `test_suite/test_20_cross_cutting_complexity_layers.py` — 497 lines, 7 tests, all 3 live `cross_cutting_complexity_layers` instances (superseding tee assignment / `ERR_STALE_TEAM_VERSION` outranking `ERR_TEE_SLOT_CONFLICT`; the repeatable tier-amendment self-loop guarded only by `expected_registration_version`; the `requires_insurance` threshold at 500000 cents for `HOLE_IN_ONE` only).
- `test_suite/test_21_consistency_model.py` — 134 lines, 2 tests, the single live `consistency_model` instance (immediate settlement: payment response already CONFIRMED; next reads carry `sold_count`, `confirmed_player_slots`, the full rollup 120000/38000/82000/6000/76000 and the beneficiary report; a second revenue channel moves net 76000 -> 123500, a delta of 47500, proving full re-derivation rather than an increment).

**One fix to an earlier file**: `test_suite/test_06_validation_priority_conflicts.py` line 195 had a hyphen substituted for the PRD's em dash inside a quoted ladder fragment (`"**Optimistic concurrency** - the supplied version guard..."`). Split into two verbatim quotes; that file now audits 14/14 fragments.

**Final coverage (scripted against both design yamls)**
- Queue A: 23/23 live difficulty instances, 47 tests, every instance >= 2.
- Queue B: 71/71 live corner instances, 102 tests, every instance >= 1. Per section: entities 12/12, state_machines 19/19, calculations 12/12, validations 14/14, endpoints 4/4, errors 2/2, rbac 4/4, cross_cutting_complexity_layers 3/3, consistency_model 1/1.
- 149 test functions, 149 `Design:` tags, 94 distinct tags. Zero tags pointing at a non-existent instance, zero pointing at an `excluded_because:` stub, zero untagged or dual-tagged tests, and every tag is the last line of its docstring.
- **Skipped instances: only the 24 `excluded_because:` corner stubs.** No live instance was dropped by the PRD-first two-condition filter, so there are no coverage gaps to report.

**Gates, all green**
- `ast.parse` on all 31 files; `pyflakes` clean over `test_suite/*.py` (run from inside `test_suite/`) and the audit script clean on every file in both directories.
- PRD-fragment audit: 481 quoted fragments across the 21 test files, 0 missing after the test_06 fix.
- No occurrence of "scaffold", the design section numbers, "queue A/B" or design-file names anywhere in the generated code; no `unittest`, mocking, `monkeypatch`, `time.sleep` or direct HTTP; the only non-`test_helpers` imports are `pytest` and conftest's path bootstrap.

**Layout** — `test_helpers/` (9 files, 3083 lines) and `test_suite/` (conftest + 21 test files, 8644 lines) both sit at the task root; nothing was created under `workspace/` (still just `INSTRUCTION.md`, `PRD.md`, `implementation/`) and `worklog.md` was not touched. `__pycache__` dirs left by the import checks were removed.

Orchestrator note: independently confirmed `test_helpers/` (9 entries) and `test_suite/` (22 entries) are at the task root and that no `test_*` directory leaked into `workspace/` (known Step 5 failure mode).

## Step 6: Generate implementation — 2026-09-04T16:30:30.000Z

The implementation is complete, verified, and smoke-tested. My server on port 18722 was killed by its exact pid (2318914); the port is free and no other process was touched.

## What was built

`workspace/implementation/` — Python 3 + Flask, in-memory dicts only, zero seeded data (verified: every list endpoint reports `total_count: 0` on a fresh boot).

Per-file line counts (3,966 lines total):

| file | lines | file | lines |
|---|---|---|---|
| derive.py | 568 | routes/outings.py | 376 |
| validate.py | 251 | routes/registrations.py | 340 |
| calc.py | 186 | routes/teams.py | 259 |
| store.py | 180 | routes/contests.py | 246 |
| serial.py | 119 | routes/allocations.py | 226 |
| errors.py | 93 | routes/contracts.py | 208 |
| lookup.py | 69 | routes/receipts.py | 170 |
| auth.py | 56 | routes/items.py | 156 |
| envelope.py | 54 | routes/players.py | 107 |
| enums.py | 52 | routes/assets.py | 106 |
| app.py | 50 | routes/tiers.py | 73 |
| | | routes/clock.py | 20 |
| | | routes/__init__.py | 1 |

Plus `start.sh` (399 B, executable, `exec python3 app.py`, pip install guarded by an import probe so per-test reboots stay fast) and `requirements.txt`.

## Verification performed

- **Structural cross-checks against the spec**: all 54 PRD endpoints are present in the Flask URL map with matching methods (no missing, no extras); all 62 error IDs in the PRD catalogue exist in `errors.ERROR_STATUS` with the exact HTTP status the catalogue pins (no missing, no extras, no status mismatches); every entity's serialized field tuple matches the SCAFFOLD field list exactly for all 11 entities (`CharitableReceipt` correctly carries `id` + `created_at` but no `updated_at`/`version` per PRD 2.3).
- **Fresh-boot behaviour**: 0.68 s from `bash start.sh` to first served request, all stores empty — safe for `--isolation per-test-server`.
- **End-to-end happy path** (all green): clock set -> outing -> contract + SIGN -> tier -> OPEN_REGISTRATION -> registration -> payment (CONFIRMED, `entitled_asset_balance` 1) -> 4 players (snapshot + `course_handicap` 13) -> team (`team_playing_handicap` 6.5 = 13 x (0.20+0.15+0.10+0.05), PROVISIONAL) -> asset -> allocation -> COMMIT/APPROVE_ARTWORK/INSTALL/VERIFY (segregation of duties correctly refused the approver's own VERIFY with 403 `ERR_SEGREGATION_OF_DUTIES`, then a second manager succeeded) -> contest + insurance bind + OPEN -> fundraising item sale + payment -> two receipts (`GR-0001`, `GR-0002`; auction deductible 30000-20000 = 10000) -> LOCK_FIELD (variant flips to LOCKED) -> CHECK_IN -> tee-assignment (OCC guard correctly rejected a stale `expected_team_version` with 412) -> pairing sheet -> START_PLAY -> score (net 68 - 6.5 = 61.5) -> contest CLOSE + award (amateur -> `MERCHANDISE_CREDIT`, claim paid, `contest_payout_cents` 0) -> FINALIZE_SCORING -> RECONCILE -> REMIT -> proceeds report.
- **Rollup arithmetic checked by hand against 3.6 step 7**: PROVISIONAL gave direct 86000 / before-fee 4000 / `admin_fee_pct` 0.05 on the *gross* base = 4500 / net -500; FINAL gave `prize_cost` 2500 (the 0.50 share actually awarded) / unclaimed 2500 / before-fee 6500 / net 2000, and REMIT accepted exactly 2000 and moved finance to DISBURSED.
- **Negative paths**: 401 for each missing/invalid auth header, 403 for a wrong role, 422 for missing/mistyped body fields and bad `limit`/`offset`, 404 `ERR_NOT_FOUND` for an unknown route, 405 for a wrong method, 409 `ERR_PRIZE_POOL_UNFUNDED` when the pool exceeded net collections, 409 `ERR_INSURANCE_NOT_BOUND` / `ERR_MISSING_TEE_ASSIGNMENT` on premature transitions, and Participant ownership enforced (own row 200, another player's row 403).

## Fixes made this session

- `routes/clock.py`: `POST /_clock/set_current_utc` now echoes `{"current_utc": ...}` instead of an empty object.
- (Earlier, carried into this session) `routes/players.py` snapshot now calls `derive.rederive_player_handicap(row, use_effective=False)` so the course handicap is actually computed; `routes/registrations.py` lifecycle allow-list tightened to `("action", "refund_cents")`; `routes/assets.py` inventory no longer touches the outing row on an undeclared trigger.

`worklog.md` was not touched, and nothing under `test_suite/` or `test_helpers/` was read or created.

Orchestrator note: Steps 5 and 6 were launched concurrently in a single assistant message, so the implementation generator's process began before `test_suite/` existed on disk — physical isolation from the test answers, not just an instruction.

## Step 7: Run tests and iterate — 2026-09-04T17:00:00.000Z

Clean 8-round sweep achieved.

## Summary

**Iterations run:** 2 (iteration 1: 164/170 in all 8 rounds, 6 deterministic failures — no flakiness; iteration 2: 170/170 in all 8 rounds).

**Final sweep artifacts on disk** (`workspace/implementation/`): `results.1.json` ... `results.8.json`, each **170 passed / 170 total**, 0 failed, 0 errors, 0 skipped.

**Tests deleted:** none. No failing test was PRD-silent at STEP 1a.

**Assertion relaxed (STEP 1b — error precedence silence), 1 test:**
- `test_suite/test_16_validations.py` -> `TestTheFourRemitConditionsPeelOffInOrder::test_receipts_then_the_version_guard_then_the_loss_are_reported_in_turn`: the first refusal now uses `validate_error_is_one_of([ERR_UNRECEIPTED_ITEMS_REMAIN, ERR_STALE_OUTING_VERSION])`. PRD 3.9 lists the unreceipted-items condition first among the four remit conditions, but 2.6 places optimistic concurrency at tier 11 above every tier-12 business rule, and 2.6's tier-12 sub-tier enumeration never mentions `ERR_UNRECEIPTED_ITEMS_REMAIN` (nor `ERR_TEAM_INCOMPLETE`, `ERR_MISSING_TEE_ASSIGNMENT`, `ERR_NO_RAIN_DATE_TERMS`, `ERR_ASSET_OCCUPIED` — so the lists are demonstrably non-exhaustive and cannot be read as excluding it from tier 12). Two PRD-faithful implementations diverge here, so the exact choice is not uniquely derivable. The remaining two rungs of the test (stale guard, then `ERR_NEGATIVE_NET_PROCEEDS` on a fresh guard) are unchanged and still exact.

**Fixes to `test_helpers/` (STEP 2 — fixture precondition inconsistent with PRD):**
- `test_helpers/fixtures.py`, new helper `check_in_registration()` — drives `CHECK_IN` through the course role.
- `test_helpers/fixtures.py`, `remit_ready_outing()` — rebuilt as `in_play_outing -> CHECK_IN -> post_score -> finalize_scoring` instead of delegating to `scored_outing`. It previously produced a `SCORED` outing with `checked_in_player_count == 0`, so reconciliation's FINAL treatment billed a zero turnout (`course_charge_cents == 0`, `net_proceeds_cents == 114000`) while the tests asserted the PRD-correct 4-player turnout (`38000` / `76000`). PRD 3.9 pins the FINAL billable count to `checked_in_player_count`, and check-in "requires the outing's play dimension to be `FIELD_LOCKED` or `IN_PLAY`", hence its placement before `FINALIZE_SCORING`. This fixed 2 tests.

**Fixes to `implementation/` (STEP 3):**
- `workspace/implementation/routes/teams.py`, `_player_ids()` — replaced the local ad-hoc list check with `validate.req_id_list(body, "player_ids")` so an empty roster is reported at the schema tier as `ERR_INVALID_REQUEST` rather than falling through to the tier-12 `ERR_TEAM_SIZE_INVALID`. PRD 2.5 lists "an array that must be non-empty is empty" among the `ERR_INVALID_REQUEST` faults and 2.6 evaluates tier 3 before tier 12. Fixed 2 tests.
- `workspace/implementation/routes/players.py`, `read_player()` — added the `own_player_only()` fence. PRD 2.1 says "addressing any other player's row is refused with `ERR_UNAUTHORIZED`" and 2.6 puts that check in the authorization tier ahead of path existence, so it governs reads, not just the handicap write. Fixed 1 test.

`worklog.md` was not touched; `SCAFFOLD*.yaml` were not read. Generated `__pycache__` / `.pytest_cache` directories were cleaned up; no stray servers left behind.

Orchestrator verification (per known failure mode of Step 7 claiming a sweep it did not leave artifacts for): independently ran `ls -la results.*.json` and parsed all eight — every file present, timestamped 16:48, each reporting `passed 170 / failed 0 / errors 0 / total 170 / skipped 0`. Step 8 is NOT skipped: Step 7 applied 3 implementation fixes plus 2 test_helpers fixes and 1 assertion relaxation.

## Step 8: Finalize PRD — 2026-09-04T17:05:00.000Z

Done. `PRD_FINALIZED.md` written with two surgical edits.

## Line counts
- `PRD.md`: 521 lines / 111,648 bytes
- `PRD_FINALIZED.md`: 521 lines / 112,098 bytes
- Line delta: 0 (+0.0%); byte delta +450 (+0.40%). Two lines revised (233, 387).

## Changes
- **3.2 (Teams paragraph, line 233)** — revise — an empty `player_ids` array is now pinned as a schema-tier `ERR_INVALID_REQUEST` rather than the tier-12 `ERR_TEAM_SIZE_INVALID`; the upper bounds keep `ERR_TEAM_SIZE_INVALID` verbatim — `implementation/routes/teams.py:90-95` -> `implementation/validate.py:161-170`.
- **3.9 (Remitting paragraph, line 387)** — revise — the four remit conditions are now explicitly ordered: the `expected_outing_version` guard is the 2.6 tier-11 check and is evaluated ahead of the three business conditions, which run in the order the paragraph already states — `implementation/routes/outings.py:333-336` (guard) vs. `implementation/routes/outings.py:350-366` (`_remit`).

## Step 7 items that needed **no** PRD change
- `test_helpers/fixtures.py` `remit_ready_outing()` / `check_in_registration()` — pure fixture bug. PRD line 205 already pins CHECK_IN to `CONFIRMED|AMENDED -> CHECKED_IN` requiring play dimension `FIELD_LOCKED`/`IN_PLAY` and re-deriving `checked_in_player_count`, and line 379 already pins the FINAL billable count to `checked_in_player_count`. Impl (`routes/registrations.py:214-233`) matches verbatim prose.
- `routes/players.py` `read_player()` + `own_player_only()` — the impl was moved *toward* the PRD, not away. 2.1 ("addressing any other player's row is refused with `ERR_UNAUTHORIZED`") plus 2.6 tier 2 (ahead of tier 4 path existence) already determine it; impl calls `own_player_only` before `get_player`. Prose kept verbatim.

## Pre-edit search log

**Edit 1 — 3.2 `player_ids`**
- (a) Subject: validation of the `player_ids` array and which tier reports each malformation, plus every producer of `ERR_TEAM_SIZE_INVALID`.
- (b) Enumerated / read: `routes/teams.py:36-39` (`only_fields`, `_player_ids` callsite), `routes/teams.py:90-95` (`_player_ids` body), `validate.py:161-170` (`req_id_list`: non-list -> `ERR_INVALID_REQUEST`; empty -> `ERR_INVALID_REQUEST`; non-string/blank element -> `ERR_INVALID_REQUEST`), `routes/teams.py:57-58` (`len < 1 or > 4` -> `ERR_TEAM_SIZE_INVALID`; the `< 1` arm is now unreachable), `routes/teams.py:59-68` (per-registration slot count -> `ERR_TEAM_SIZE_INVALID`), `errors.py:64` (409). Grepped `ERR_TEAM_SIZE_INVALID` and `req_id_list` across all of `implementation/` — `req_id_list` has exactly one callsite, so no other endpoint's array semantics are touched. Also re-read 2.5's `ERR_INVALID_REQUEST` fault list and 2.6 tier 3 vs tier 12, and 4's `POST /outing-ops/teams` row (line 424, no conflicting claim).
- (c) Adjustment: wrote "so it is caught at the schema tier" rather than naming the code path or claiming the team-size rule lost its lower bound — the tier-12 rule still nominally holds "between one and four", it is simply unreachable from below. Kept the existing "must be non-empty" clause instead of deleting it, so the requirement itself is not weakened, only its reporting tier pinned.

**Edit 2 — 3.9 remit condition ordering**
- (a) Subject: precedence of a version guard relative to the business conditions of the same request — specifically `ERR_STALE_OUTING_VERSION` vs `ERR_UNRECEIPTED_ITEMS_REMAIN` / `ERR_NEGATIVE_NET_PROCEEDS` / `ERR_REMITTANCE_AMOUNT_MISMATCH`.
- (b) Enumerated / read: `routes/outings.py:300-347` (`finance_transition`: schema -> state precondition per action -> version guard at :333 -> dispatch), `routes/outings.py:350-377` (`_remit`: unreceipted registrations -> unreceipted `PAID` items -> `net_proceeds_cents <= 0` -> remittance mismatch -> contract `SETTLED` freeze). Then, to avoid a claim inconsistent off the Step 7 site, checked the other two version-guarded endpoints named by 2.7: `routes/teams.py:146-150` (guard at :148, ahead of all four tee-sheet business checks at :159-220) and `routes/registrations.py:140,160-172` (guard at :160, after cross-outing/state/open-field, ahead of `ERR_TIER_INVENTORY_EXHAUSTED` and `ERR_PAYMENT_AMOUNT_MISMATCH`). All three agree with 2.6 tier 11 sitting above tier 12. Grepped `ERR_UNRECEIPTED_ITEMS_REMAIN` — raised only inside `_remit`, nowhere else.
- (c) Adjustment: scoped the sentence to this paragraph's four conditions and justified it by reference to the existing 2.6 ladder, rather than adding a new general rule to 2.6 or 2.7 — the ladder already says tier 11 precedes tier 12, so no global text needed changing, and a 2.6 edit risked re-describing the other two guards. Also deliberately did **not** add `ERR_UNRECEIPTED_ITEMS_REMAIN` to 2.6's tier-12 sub-tier enumerations (those lists are demonstrably non-exhaustive; inserting it would have implied a sub-tier and an intra-sub-tier position the impl does not exhibit).

Orchestrator note: confirmed `PRD_FINALIZED.md` exists and is NOT byte-identical to `PRD.md` (two revised lines, +450 bytes).

## Step 9: Complete PRD — 2026-09-04T17:35:00.000Z

Run as THREE SEQUENTIAL PASSES partitioned by implementation module (a single-agent scan over ~4000 lines / 25 modules is the known failure mode where PRD_COMPLETED.md comes back byte-identical to its source). Pass 1 performed the `cp` from `PRD_FINALIZED.md`; passes 2 and 3 were explicitly forbidden from running `cp` and edited the existing file in place with the Edit tool only.

### Pass 1 of 3 — cross-cutting / infrastructure (app, auth, envelope, enums, errors, lookup, serial, store, validate, routes/clock, start.sh)

`cp` ran first thing; only `PRD_COMPLETED.md` was edited (16 distinct lines, all in-paragraph, no new sections, line count unchanged at 521). Sizes after edits: `PRD_FINALIZED.md` 521/112098, `PRD_COMPLETED.md` 521/119243. **Counts: 13 ambiguity-pins, 3 mismatch-revisions.**

- 2.1 — revise — mismatch — auth was claimed "the very first check the server performs on any request"; routing-level 404/405 precede it, so scoped to "any request that reaches a declared endpoint"; also pinned blank/whitespace `X-User-ID` -> 401, case-sensitive role match, and `X-User-ID` examined before `X-User-Role` — `auth.py:34-42`, `app.py:26-33`
- 2.1 — insert — ambiguity — Participant ownership is an exact string compare of the path id at tier 2 *before* the row is resolved, so an unknown player id yields `ERR_UNAUTHORIZED` not `ERR_PLAYER_NOT_FOUND`; applies to the two single-player endpoints only, not the list — `auth.py:53-56`, `routes/players.py:64,94`
- 2.2 — insert — ambiguity — `api_request_id` is `req_` + exactly 20 upper-case-alphanumeric chars (24 total) — `store.py:130-132`
- 2.2 — insert — ambiguity — `api_request_timestamp` is real wall-clock, not the logical clock — `envelope.py:16-20`
- 2.2 — insert — ambiguity — serialized resources always carry the complete declared field set with unset properties present as `null`, and expose nothing outside it — `serial.py:110-113`
- 2.2 — insert — ambiguity — the four pagination `meta` fields are absent from single-object responses — `envelope.py:23-26,32-39`
- 2.2 — revise — mismatch — error envelope was scoped to "4xx status codes"; 5xx uses it too — `app.py:35-40`
- 2.3 — insert — ambiguity — `limit`/`offset` must be plain integers (`abc`, `10.5` rejected); `offset` has no ceiling and an over-the-end offset returns an empty array with true `total_count` and `has_more` false; pagination validated ahead of endpoint filters; undeclared query params ignored; identifier filters matched literally (empty list, not 404); boolean filters accept `true/false/1/0` any case — `validate.py:196-241`, `routes/registrations.py:79-88`
- 2.3 — insert — ambiguity — `created_at` ties broken by ascending creation order, and ties are the normal case because the logical clock only moves when called — `store.py:173-174`
- 2.4 — insert — ambiguity — `id` is a random (v4) UUID in canonical lower-case hyphenated 36-char form — `store.py:126-127`
- 2.4 — insert — ambiguity — a newly created row is returned at `version` 1 with `updated_at == created_at` even when the same request derives fields onto it — `store.py:135-171`
- 2.4 — insert — ambiguity — clock endpoint accepts only the mandatory `current_utc`, the clock never ticks on its own, and the call answers 200 with `data.current_utc` canonicalised — `routes/clock.py:13-20`, `store.py:107-112`
- 2.5 — revise+insert — mismatch — the universal "negative `_cents`/`_count` rejected" claim is false for the signed amend-tier `amount_cents`, and unknown-key rejection covers *any* undeclared key, not just server-computed fields; plus pins on no coercion (string not-> number, bool not-> int), `null` == omitted, non-blank required strings, unparseable/non-object body vs. absent body, timestamps accepted with 0 or 1-9 fractional digits and canonicalised to 3 by truncation (`+00:00` rejected), and the intra-tier fault order (body parse -> undeclared key -> declared fields in order; presence -> type -> range) — `validate.py:15-190`, `store.py:56-96`, `routes/registrations.py:141`
- 3.9 — insert — ambiguity — the proceeds report is the outing resource plus an added `outing_id`, and is a pure read that does not advance `version` — `serial.py:116-119`, `routes/outings.py:92-96`
- 4 — insert — ambiguity — trailing slash insignificant; `action` is a mandatory enum whose set is exactly that endpoint's list, so a borrowed/unknown action is `ERR_INVALID_REQUEST` at tier 3, never `ERR_INVALID_STATE_TRANSITION` — `app.py:18`, `enums.py:8-10`, `validate.py:71-75`
- 5 — insert — ambiguity — three identifiers absent from the table: unknown path -> 404 `ERR_NOT_FOUND`, wrong method -> **405** `ERR_INVALID_REQUEST` (the one place that id is not 422), internal fault -> 500 `ERR_INTERNAL`; all decided before authentication and all carrying the standard envelope — `app.py:26-40`

Verified by booting the server on port 10731 (now stopped) — the 404/405/500 identifiers, trailing-slash tolerance, blank-header 401, clock canonicalisation, pagination bounds/precedence, insertion-order listing, and uuid4/`version 1` stamps were all confirmed empirically. Also machine-checked that 5's 62 error rows match `errors.ERROR_STATUS` exactly (no diffs) and that every `enums.py` value appears in the PRD.

### Pass 2 of 3 — calc.py, derive.py, routes/{outings,contracts,tiers,registrations,players,teams}.py

Did **not** run `cp` — every change was a surgical `Edit` against the existing `PRD_COMPLETED.md`, so pass 1's cross-cutting edits are intact (spot-checked). Size before first edit `521 119243` -> after last edit `521 127069` (+7,826 bytes, line count unchanged). **Counts: 19 ambiguity-pins, 12 mismatch-revisions (31 changes).**

- 3.2 — revise — mismatch — amend-tier's five refusal conditions reordered to the real evaluation order (cross-outing -> player_slots -> registration state -> open-field -> version -> inventory cap -> payment delta), and a foreign tier now reports `ERR_CROSS_OUTING_REFERENCE` rather than `ERR_TIER_NOT_FOUND` — `routes/registrations.py:147-172`
- 3.9 — revise — mismatch — dropped the claim that "every finance transition" recomputes the rollup; `REMIT` recomputes nothing — `routes/outings.py:303-330`
- 3.3 — revise — mismatch — `prize_award_cents` starts at 0, not null — `routes/teams.py:77`
- 2.8 — revise — mismatch — `guaranteed_player_count` added to the money-term cascade set; "every player" softened to the players the cascade actually reaches — `routes/contracts.py:24-31`
- 2.6 — revise — mismatch — the `ERR_CONTRACT_NOT_SIGNED` worked example no longer uses `LOCK_FIELD`, which never checks contract signature — `routes/outings.py:150-205`
- 3.1 — revise — mismatch — `POSTPONE` accepts a body-supplied `rain_date` with precedence over the stored one — `routes/outings.py:186-196`
- 3.3 — revise — mismatch — a reopen actively clears `effective_handicap_index` rather than leaving it null — `derive.py:120-133`
- 4 — revise — mismatch — a team's players may be funded by several registrations of the same outing, not one — `routes/teams.py:59-68`
- 3.2 — revise — mismatch — waitlisted cancellation runs no rollup — `routes/registrations.py:270-280`
- 3.8 — revise — mismatch — ranking key 7 falls back to creation order after `created_at` — `derive.py:434-437`
- 3.2 — revise — mismatch — waitlist candidate ties break on `created_at` then creation order — `derive.py:482`
- 3.5 — revise — mismatch — tee assignment has no play-state precondition; the version guard is evaluated first, before all four checks — `routes/teams.py:146-150`
- 3.5 — insert — ambiguity — same-wave carts are shared freely; only cross-wave holds are turnaround-tested — `routes/teams.py:176-193`
- 3.5 — insert — ambiguity — an unconfigured wave window is `ERR_WAVE_WINDOW_VIOLATION`, and makes the turnaround test a no-op — `routes/teams.py:124-133, 200-201`
- 3.5 — insert — ambiguity — the 15-minute prep window is tested against the wave start for every assignment, reported as `ERR_CART_DOUBLE_BOOKED` — `routes/teams.py:194-197`
- 3.5 — insert — ambiguity — cart-allowance is tested twice: absolute `cart_number` bound, then distinct carts within the wave — `routes/teams.py:210-220`
- 3.5 — insert — ambiguity — `slot_occupancy_end` is derived from the contract's `tee_interval_minutes` (default 10) and `cart_allowance_count` defaults to 40 with no contract — `routes/teams.py:151-154, 226-228`
- 3.2 — insert — ambiguity — entitlement release keeps the oldest allocations and releases the excess in `(created_at, _seq)` order — `routes/registrations.py:194-201`
- 3.2 — insert — ambiguity — amending to the same tier skips the inventory-cap test entirely — `routes/registrations.py:164-165`
- 3.2 — insert — ambiguity — promotion side effects enumerated (confirm stamp, player snapshots, entitlement re-seed, sold_count and outing counters) and the cap/capacity re-tests explicitly not performed — `derive.py:487-505`
- 3.6 — insert — ambiguity — the automatic reversal stamps the cancelling user and targets the live forward receipt of that registration only — `derive.py:540-566`
- 3.9 — insert — ambiguity — billable player count and the F&B shortfall basis pinned to the counter values, not a live recount — `routes/outings.py:238-268`
- 3.9 — insert — ambiguity — `run_rollup` re-derives the outing counters and the receipted total as a pre-pass before step 1 — `derive.py:290-300`
- 3.9 — insert — ambiguity — `_remit` settles `settled_charge_cents = course_charge + fnb_shortfall - rain_credit` — `routes/outings.py:330-345`
- 3.3 — insert — ambiguity — a team with no members carries `team_playing_handicap` of `0.0`, not null — `calc.py:150-160`
- 3.3 — insert — ambiguity — a handicap-index update is refused in `FIELD_LOCKED`/`IN_PLAY`/`SCORED` and always re-derives the team under the `PROVISIONAL` variant — `routes/players.py:88-110`
- 3.3 — insert — ambiguity — the index update never re-snapshots `handicap_index_at_confirm` and re-derives the player's `course_handicap` off the raw index — `routes/players.py:104-106`
- 3.1 — insert — ambiguity — pairing-sheet ordering pins null placement: nulls last on `wave`, `starting_hole` and `tee_time`, then `created_at`, then creation order — `routes/outings.py:352-372`
- 2.3 — insert — ambiguity — contract numeric-term bounds pinned (`slope_rating`, `course_rating`, `par`, `tee_interval_minutes`, `cart_allowance_count`, `rain_date_credit_pct`, `cancellation_notice_days`) — `routes/contracts.py:33-58`
- 3.9 — insert — ambiguity — `remittance_cents`/`remittance_reference` are required by `REMIT` alone and accepted-but-ignored on `RECONCILE`/`REOPEN` — `routes/outings.py:303-312`
- 3.1 — insert — ambiguity — the contract-lifecycle request accepts `void_reason` and all amendable terms regardless of `action`, ignoring the ones the action does not use — `routes/contracts.py:102-104`

`routes/tiers.py` needed no changes: every default and bound (`inventory_cap` 999/min 1, `gsv_cents` 0, `entitled_asset_type` `NONE`, `entitled_asset_count` 0, `player_slots` 0..4, `ERR_TIER_CODE_DUPLICATE` before row creation) already matched 3.2 exactly.

### Pass 3 of 3 — routes/{assets,allocations,contests,items,receipts}.py

No `cp` was run — edited the existing `PRD_COMPLETED.md` in place with the Edit tool only. `wc -lc` before first edit `521 127069` -> after last edit `521 130797`. **Counts: 12 ambiguity-pins, 6 mismatch-revisions (15 Edit calls).**

- 3.4 (asset creation) — revise — mismatch — `hole_number` no longer claimed to "stay null" for carts/beverage stations: it may be supplied and is stored as given; also pinned that its absence on a hole sign/contest is `ERR_INVALID_REQUEST` raised before the outing resolves — `routes/assets.py:38-40`
- 3.4 (asset creation) — revise — mismatch — `exclusive` redefined to what impl enforces (at most one live allocation on *that unit*, whatever its capacity) instead of a cross-unit "same asset_type on the same hole" rule that impl never checks — `routes/allocations.py:73-77`
- 3.4 (asset creation) — insert — ambiguity — building inventory has no precondition on the outing's play dimension — `routes/assets.py:26-58`
- 3.4 (allocation creation) — revise — mismatch — cross-outing is checked **before** the open-field gate (PRD had the order reversed); the CART/BEVERAGE_STATION window requirement is `ERR_INVALID_REQUEST` evaluated after both body refs resolve and ahead of cross-outing; windows supplied for a hole sign/contest are accepted and discarded to null — `routes/allocations.py:37-50`
- 3.4 (allocation ladder) — insert — ambiguity — a tier entitling `NONE` (or an unresolvable tier) fails the `ERR_ASSET_TYPE_MISMATCH` comparison for every unit — `routes/allocations.py:55`
- 3.4 (service window) — insert — ambiguity — the conflict scan skips `RELEASED` allocations and allocations carrying no window — `routes/allocations.py:106-111`
- 3.4 (fulfillment) — insert — ambiguity — `waived_reason` is accepted alongside any action; only `WAIVE` requires and records it — `routes/allocations.py:153-156`
- 3.6 (contest creation) — insert — ambiguity — `yardage` may never be negative — `routes/contests.py:38`
- 3.6 (contest creation) — insert — ambiguity — staging has no precondition on the outing's play dimension — `routes/contests.py:29-45`
- 3.6 (insurance binding) — revise — mismatch — pinned the three-test order: insurance dimension must still read `NONE` (checked first), then the lifecycle state, and only last the `cap >= 1` floor, which unlike the rest of the schema tier runs after both state tests — `routes/contests.py:122-129`
- 3.6 (award) — insert — ambiguity — an omitted `witness_count` is recorded as 0 — `routes/contests.py:189`
- 3.6 (claim adjudication) — insert — ambiguity — a null `yardage` counts as below the minimum whatever the minimum reads, so it always denies on the first test — `routes/contests.py:224`
- 3.7 (item creation) — insert — ambiguity — listing an item has no play-dimension precondition — `routes/items.py:24-49`
- 3.7 (item lifecycle) — insert — ambiguity — `void_reason` is validated then discarded, not stored; `VOID` is an edge out of `SOLD` alone so a paid lot cannot be voided; `RELIST` leaves `void_count` standing; both actions recompute the rollup — `routes/items.py:130-156`
- 3.7 (receipt issuance) — insert — ambiguity — neither subject's status is a precondition; an item below `PAID` is receipted for its current `collected_cents` (0 when still `LISTED`) and left at its status — `routes/receipts.py:84-119`
- 3.7 (reversal) — revise — mismatch — a reversal arises by three equivalent paths (dedicated capability, issuance with `receipt_kind` `REVERSAL`, cancellation cascade); both caller-driven paths answer `201 Created`; `reversal_reason` is discarded — `routes/receipts.py:63-70, 160-170`
- 3.7 (reversal) — insert — ambiguity — no reversal is subject to the 2.9 segregation-of-duties rule, which governs forward receipts alone — `routes/receipts.py:84-88` vs `routes/receipts.py:66-70`
- 3.9 (rollup trigger list) — revise — mismatch — added "a fundraising void or relist" to the events that recompute the rollup — `routes/items.py:152-155`

Prior passes confirmed intact by spot-check (pass 1's `api_request_id` clause, the 5 `ERR_INTERNAL`/405 paragraph, pass 2's tier-amendment release rule, the 3.4 balance clause).

### Orchestrator verification

- `PRD.md` 521 / 111,648 B; `PRD_FINALIZED.md` 521 / 112,098 B; `PRD_COMPLETED.md` 521 / 130,797 B.
- `PRD_COMPLETED.md` is NOT byte-identical to `PRD_FINALIZED.md` (56 revised lines, +18,699 B, +16.7%) — the known no-op failure mode did not occur.
- Tail check: file ends on the `ERR_REMITTANCE_AMOUNT_MISMATCH | 402` row under `## 5. Error Code Catalogue`, 28 headings, no mid-sentence truncation.
- **Implementation untouched since the clean sweep**: `find workspace/implementation -newermt '2026-09-04 16:49' -type f` returned only `.pyc` bytecode from pass 1's smoke boot — zero source files modified, so the 8/8 x 170/170 results remain valid for the shipped code. `__pycache__` and `.pytest_cache` removed afterwards.

PIPELINE COMPLETE.
