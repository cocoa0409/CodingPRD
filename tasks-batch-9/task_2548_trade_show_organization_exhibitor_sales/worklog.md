# Worklog — task_2548_trade_show_organization_exhibitor_sales

## Step 1: Create task directory — 2026-09-03T09:13:00.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2548_trade_show_organization_exhibitor_sales` and its `workspace/` subdirectory. Index 2548 was pre-assigned by the orchestrating caller; no auto-allocation scan was performed (other pipelines run concurrently on this host).

## Step 2: Generate Scaffold — 2026-09-03T11:40:00.000Z

Done. All three artifacts are complete and the lint is clean.

**Output directory** `/home/ubuntu/github/CodingPRD/tasks/task_2548_trade_show_organization_exhibitor_sales/`

```
  3144 SCAFFOLD.yaml                  (171,751 bytes)
  2309 SCAFFOLD_DIFFICULTY_DESIGN.yaml (152,562 bytes)
  4066 SCAFFOLD_CORNER_DESIGN.yaml    (275,074 bytes)
  9519 total
```
(the pre-existing `worklog.md` and empty `workspace/` were already in the directory and were not touched)

**Structure verified**
- `SCAFFOLD.yaml` top-level keys: `scenario, domain_name, api_prefix, complexity_profile, response_envelope, entities, state_machines, concurrency_rules, calculations, validations, endpoints, errors, roles` — contains neither `scaffold_difficulty_design` nor `scaffold_corner_design`.
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml`: single top-level key `scaffold_difficulty_design` (9 rule groups, 24 instances).
- `SCAFFOLD_CORNER_DESIGN.yaml`: single top-level key `scaffold_corner_design`, 9 sections / 72 instances: entities 12, state_machines 16, calculations 15, validations 9, endpoints 4, errors 6, rbac 3, cross_cutting_complexity_layers 6, consistency_model 1. 21 of those are `excluded_because` stubs; every cited `difficulty_instance` resolves to a real name in the difficulty file, and no stub carries a `test_recipe` while every non-stub does.

**Scenario/difficulty**: 13 entities / 53 endpoints / 66 errors / 63 validations / 10 state machines / 17 calculations / 6 concurrency rules / 5 roles — `expert_plus` band. All 66 §1.6 error ids are referenced by at least one §1.8/§1.9 instance (verified mechanically; zero uncovered).

**Work finished this session**: the final `cross_cutting_complexity_layers` entries (`the_rebook_occ_field_pins_the_target_edition_not_the_source` for `rebook-stale-target-show`, `terminating_a_venue_contract_is_guarded_by_the_contracts_own_version` for `venue-contract-terminate-stale` with `ERR_STALE_VENUE_CONTRACT_VERSION`, plus the `cascading_side_effects` and `dual_variant_calculation` stubs) and the `consistency_model` section (`every_derived_field_is_already_settled_in_the_writing_response`).

**One lint fix**: the first run reported a single violation — `structural_and_existence_checks_run_in_priority_order` passed `expected_show_version: "1"` as a literal. It now creates an unrelated 2027 Show in setup, captures `osv: $.data.version` from `GET /shows/${other_show_id}`, and sends `expected_show_version: "${osv}"` against the nonexistent show id, which preserves the claim (priority-10 `ERR_SHOW_NOT_FOUND` outranks the priority-30 OCC check) with a server-sourced version.

```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

Coverage line from the same clean run: 53 endpoints declared, 13 entities declared, 24 §1.8 instances scanned, 51 §1.9 instances scanned (stubs excluded), 1120 calls scanned.

The hard constraint was honored throughout: no sibling task directory under `tasks/` was listed, globbed, grepped, or read, and the stray `skills/prd-bench-scaffold-generator/SCAFFOLD_CORNER_DESIGN.yaml` was never opened. Everything derives from the verbatim scenario plus `SKILL.md` and `references/claim-extraction-guide.md`.

## Step 3: Copy Shared Files — 2026-09-03T11:41:00.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` to `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-03T12:02:00.000Z

PRD generation is complete and verified.

## Output
`/home/ubuntu/github/CodingPRD/tasks/task_2548_trade_show_organization_exhibitor_sales/workspace/PRD.md` — **475 lines**, built entirely with chunked `cat >> PRD.md << 'PRDEOF'` appends (no single giant Write, no truncation).

**Structure:** §1 Introduction · §2 Global Specifications (11 domain-derived subsections, 2.1 RBAC through 2.11 Order of Evaluation, with §2.2 copied byte-for-byte from `section-2.2-response-structure.md`) · §3 Business Logic (9 subsections, 3.1 hall contracting → 3.9 on-floor services/enforcement/rebooking/close) · §4 Endpoint Definitions (4-column table) · §5 Error Code Catalogue (2-column table).

**Final heading:** `## 5. Error Code Catalogue`. The file ends at a real section boundary — the last table row `| \`ERR_DEPOSIT_EXCEEDS_INVOICE\` | 422 |` — not mid-sentence. No audit footer or PASS report was written into the document.

## Hard Contract verification

**Contract 1 — Field-Name Coverage: PASS.** Two independent extraction passes.
- Pass 1: 154 required identifiers (entity `fields[].name` + endpoint `input:` identifiers + `occ_field` names) → 1 missing (`target_status`), fixed by adding it to the `SELLING → ON_SITE` sentence in §3.9. Re-run: 0 missing.
- Pass 2: 163 required identifiers using a different parse (all `input:` lines regardless of shape, all inline `output: {...}` keys including the post-show-report projection `total_registrations`, `attendance_quality_index`, `exhibitor_lines`, etc., plus a regex-independent field-name sweep) → 0 missing.
- Note: my first check run reported 136 false "missing" — the checker's backtick pairing was thrown off by the fenced ```json blocks in §2.2; stripping fences first gave the real result.

**Contract 2 — Rule Coverage: PASS.**
- All 66 catalogued error identifiers appear in the PRD, and every `validations[].error_id` is present (0 gaps); no invented error ids (PRD ∖ scaffold = ∅).
- All 39 declared state-machine transitions across the 9 machines appear as explicit `FROM → TO` arrow pairs. Five (`PLANNING → CANCELLED`, `PROPOSED → CANCELLED`, `PARTIAL → BREACHED`, `PENDING → DELIVERED`, `PENDING → WAIVED`) were prose-covered but lacked the pair; arrows were added in §3.7/§3.9.
- All 6 concurrency rules with their `occ_field` names and 412 error ids are in §2.5; all 16 calculations (12 business + 4 conservation invariants) are rendered as prose with their pinned rounding/evaluation orders and anti-pattern warnings (two-pass lead-quality rounding, pre-discount bundle-tier selection, expedite fee added after rounding, category weight applied once to the summed raw score); sibling-branch symmetry written explicitly for `UPHELD`/`WAIVED`, `EXERCISED`/`FORFEITED`, `ADVANCE`/`FLOOR`, and cascade vs. exhibitor-initiated cancellation.
- Constants spot-audited against the scaffold's 42 constant blocks (location/zone multipliers, volume and bundle tiers, tier floors, decay, deposit and cancellation bands, penalty and screening tables) — all present in prose.

**Contract 3 — §3 Path Purity: PASS.** Zero backticked tokens in §3 start with `/`, are a bare HTTP method, or combine method+path. Paths and methods appear only in §2.1/§2.5 cross-references and the §4 table.

**Extra cross-checks:** §4 contains all 53 scaffold endpoints with zero extras, and every row's `Authorized Role(s)` set matches the scaffold's `roles:` exactly (0 mismatches). §5 has exactly 66 rows.

The two withheld design files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were never opened, grepped, or referenced, and no sibling task directory was read.

**Orchestrator truncation check (per pipeline guard):** independently verified — 475 lines, tail ends at the completed final table row of §5 (`ERR_DEPOSIT_EXCEEDS_INVOICE`), final heading `## 5. Error Code Catalogue`, all 5 top-level sections and all 9 §3 subsections present. Not truncated; no regeneration needed.

## Step 6: Generate Implementation — 2026-09-03T12:50:00.000Z

Implementation complete and verified.

## What was done

Finished and validated the Python + Flask implementation in `/home/ubuntu/github/CodingPRD/tasks/task_2548_trade_show_organization_exhibitor_sales/workspace/implementation/`.

**Endpoint coverage is exact.** I diffed Flask's `url_map` against the 53 endpoints declared in `SCAFFOLD.yaml`: 53 declared, 53 live, zero declared-not-live, zero live-not-declared.

**Error catalogue is exact.** I diffed `errors.py:HTTP_STATUS` against all 66 entries of the scaffold's `§1.6 Error Code Catalog`: 0 status mismatches, 0 missing, 0 extra.

## Bugs found and fixed this session

1. `validate.datetime_field()` returns a `datetime`, not a string, but three call sites treated it as a string. In `routes/clock.py` this made `db.clock = None`, so **every** response carried `"api_request_timestamp": null` and `POST /exhibitors` returned `ERR_INTERNAL` 500 (`AttributeError: 'NoneType' object has no attribute 'year'` at `calc.py:423`). Patched `routes/clock.py`, `routes/appointments.py` (`window_start`/`window_end`) and `routes/floor.py` (`ordered_at`, `scanned_at`) to use the datetime directly and `fmt_dt(...)` when storing.
2. `calc.sponsor_discount_floor` was referenced by `routes/sponsorship.py` but did not exist — added to `calc.py`.
3. `routes/appointments.py` called `validate.re_int` as a parser; `re_int` lives in `response.py` and is a predicate. Fixed.
4. `routes/floor.py` had the nonsense expression `min(limits) if limits else show and None`. Fixed.
5. SoD comparisons could false-positive when `X-User-ID` was absent on both sides — added `is not None` guards for `reported_by_user_id`, `proposed_by_user_id`, `last_offer_by_user_id`.

## Verification performed

- **End-to-end flow** (venue contract → execute → show → 2 booths → publish → exhibitor → appointment → advance round → exercise → counter → reoffer → sign → sponsorship package/deal/sign/obligations → registration → service order → lead scan → citation → adjudicate → close → post-show report → rebook): all green. Spot-checked derived money against the PRD prose — `attrition_settlement_cents` 71,280,000 = 39,600 sqft × 1800 (PRD line 333), `certified_priority_points` 27 = 8 space + 4 spend + 25 fulfillment − 10 penalty (PRD line 211), bundle discount 2.5%, `points_awarded` 8, ADVANCE-rate service line 13,600.
- **Two error batteries** covering ~70 assertions, both now fully green: existence (all 11 404s), 405/404 routing, pagination bounds, structural-before-auth ordering, all three SoD legs, OCC 412s on show and venue contract, floor posture FROZEN, `BOOTH_MERGED`, `BOOTH_NOT_IN_SHOW`, appointment window shape/closed/state/desk capacity, negotiation-round exhaustion, discount approval + cap, deposit min/max, sponsorship inventory/exclusivity/price floor, obligation resolve + waiver reason, suspension at 30 penalty points and reinstatement, rebook target validity, cancellation waterfall.
- Notably, four of my initial expectations were wrong, not the code: contract-status (priority 24) correctly precedes money (59-63); SoD (priority 7) correctly precedes discount cap; `target_status: PLANNING` is correctly `ERR_VALIDATION` since the scaffold declares only `SELLING|ON_SITE|CLOSED|CANCELLED`; and `purchasing_authority`/`annual_spend_band` are required for every registration category.

## Constraint compliance

- **In-memory only:** grep for `sqlite|open(|json.dump|json.load|/tmp|pickle|shelve` across all modules returns only false positives (`require_violation_open`). No disk state.
- **No seeding:** two consecutive `start.sh` boots each accepted the *same* `legal_name` with 201 (case-folded uniqueness would have rejected a persisted row) and reported `total_count: 0` booths.
- **Boot verified** via `PORT=<free port> bash start.sh`; the two previously-500 paths now return 200/201 with a real `api_request_timestamp`. Every server was killed by resolving the pid from `ss -ltnp` on its own port — never a broad `pkill`.
- All 21 Python files pass `ast.parse`.

## Per-file line counts (3,630 total)

`app.py` 54 · `calc.py` 653 · `db.py` 152 · `errors.py` 97 · `guards.py` 190 · `middleware.py` 59 · `response.py` 83 · `services.py` 324 · `validate.py` 216 · `views.py` 282 · `start.sh` 8 · `requirements.txt` 1
`routes/`: `__init__.py` 0 · `appointments.py` 141 · `booths.py` 120 · `clock.py` 18 · `contracts.py` 297 · `exhibitors.py` 77 · `floor.py` 229 · `registrations.py` 98 · `shows.py` 186 · `sponsorship.py` 231 · `venue_contracts.py` 114

**Note:** Steps 5 and 6 were launched concurrently in a single orchestrator message, so the implementation generator could not read `test_suite/` (the directory did not exist at its spawn time).

## Step 5: Generate Unit Tests — 2026-09-03T14:00:00.000Z

Generation is complete. Both output directories are finished and audited.

## What was produced

**`test_helpers/` — 9 files, 2,562 lines**
`constants.py` 163 · `types.py` 447 · `api_errors.py` 162 · `api_client.py` 292 · `factories.py` 333 · `test_users.py` 89 · `assertions.py` 360 · `fixtures.py` 609 · `__init__.py` 107

**`test_suite/` — 19 files, 7,386 lines, 119 tests**
`conftest.py` 11 · `test_01` 219/5 · `test_02` 325/6 · `test_03` 219/4 · `test_04` 354/6 · `test_05` 329/6 · `test_06` 326/6 · `test_07` 328/6 · `test_08` 294/4 · `test_09` 354/6 · `test_10_entities` 522/12 · `test_11_state_machines` 638/10 · `test_12_calculations` 422/6 · `test_13_validations` 583/8 · `test_14_endpoints` 386/4 · `test_15_errors` 907/14 · `test_16_rbac` 638/10 · `test_17_cross_cutting` 396/4 · `test_18_consistency` 135/2 (lines/tests)

## Audits (all green)

- **Coverage:** 24/24 non-stub Difficulty instances (49 tests) and 51/51 non-stub Corner instances (70 tests). Zero uncovered non-stub instances; the ~22 `excluded_because:` stubs got no tests.
- **Design tags:** every test function has exactly one `Design:` line, it is the last line of the docstring, and every tag resolves to a real non-stub instance name in the source yaml. 0 untagged, 0 dual-tagged, 0 dangling, 0 stub-tagged.
- **PRD citations:** `bad fragments: 0` on all 18 test files — every quoted span survives a literal grep of `PRD.md`.
- **Scaffold hygiene:** no occurrence of "scaffold", `§1.x`, "queue A/B", `test_recipe`, `claim_type`, etc. anywhere in `test_suite/` or `test_helpers/`.
- **Static:** pyflakes clean on all of `test_suite/`; every module imports; a custom attribute audit confirms every `fx.*`, `f.*`, `client.*`, `ApiErrorId.*` and status-enum reference actually exists.

## Notable findings and fixes this session

- **Latent bug caught in already-written files.** PRD line 307 states "Rebooking, lead scanning and floor-rule citation are legal only while the edition is `ON_SITE`." Two fixtures created citations against a `SPACE_SELECTION` show, which would have been answered `ERR_INVALID_SHOW_STATUS` and failed the assertion. Fixed by moving citation creation out of the shared helper and into the individual test after a `SELLING → ON_SITE` walk, in both `test_15_errors.py::_four_family_env` and `test_16_rbac.py::_self_approval_env` — the helpers themselves have to stay in `SPACE_SELECTION` because sibling tests book appointments and re-offer contracts, which are barred after selling closes. All lead-scan sites were checked and were already correctly `ON_SITE`.
- **11 non-verbatim quotes fixed** in the queue-A files written before the quote auditor existed (`test_01`, `test_02`, `test_03`, `test_05`, `test_09`). Two of them were bold-marker mismatches — the PRD writes `**Money last**, in this order:` and `**Referential coherence**, in this order:`, so the asterisks had to be kept.
- **New work:** finished `test_16_rbac.py` (third rbac instance — peer roles sharing booth creation, service orders, citations, and the `FloorManager`-may-deliver-but-never-waive restriction on the resolve endpoint, `ERR_ROLE_NOT_PERMITTED` 403); wrote `test_17_cross_cutting.py` (all four OCC instances: one stale `expected_show_version` across create/sign/exercise, the stale combine leaving the 700 sqft partition untouched, the rebook pinning the *target* edition, and terminate's distinct `ERR_STALE_VENUE_CONTRACT_VERSION` with its cancellation cascade); wrote `test_18_consistency.py` (the sign response already carries the frozen 1556280 invoice and 8 points; the first read of show/booth/exhibitor agrees at 400/0/200, ratio 67, `ASSIGNED`, provisional 8 vs certified 0).
- No files under `workspace/implementation/` were read or written, and no sibling task directory was touched.

## Step 7: Run Tests and Fix — 2026-09-03T15:10:00.000Z

Two iterations of the 8-round parallel stability sweep (`--isolation per-test-server`, all 8 rounds concurrent under `setsid nohup`, joined with `wait`).

- **Iteration 1:** 110/119 in all 8 rounds. Nine failures, identical in every round — no flakiness anywhere in the suite.
- **Iteration 2:** **119/119 in all 8 rounds.**

### Tests deleted
None. Every failing assertion traced to a verbatim PRD sentence; all nine were either a test-artifact defect or a genuine implementation gap.

### Fixes to `test_suite/`
- `test_02_combinatorial_formula.py::test_thousand_sqft_contract_prices_both_lines_at_the_volume_tier` — expected `invoice_total_cents == space_fee_cents` and `bundle_discount_pct == 0`, but PRD §3.5 selects the bundle tier from the *pre-discount subtotal*, and 4,269,257 cents clears the two-million band with no sponsorship attached. Corrected to `bundle_discount_pct 2.5`, `bundle_discount_cents 106731`, `invoice_total_cents 4162526`. The implementation was right.
- `test_10_entities.py::test_a_planning_edition_reads_back_with_a_zeroed_area_ledger` and `test_11_state_machines.py::test_a_floor_plan_with_no_booths_cannot_be_published` — both asserted `net_sellable_sqft is None` on an unpublished edition, contradicting the very sentence they quote ("every area and money ledger — `net_sellable_sqft`, ... — initialised to zero, with `advance_order_deadline` unset until the floor plan is published"). Corrected to `== 0`; the `advance_order_deadline is None` half was already right.
- `test_10_entities.py::test_a_recorded_scan_can_only_ever_be_re_read` — asserted a byte-exact `scanned_at` echo (`2027-03-05T10:05:00Z`). PRD §2.4 pins the canonical timestamp rendering at three fractional digits and lists `scanned_at` among the timestamps the system writes, so whether the server echoes the client's rendering or restates it canonically is not uniquely derivable. Per the partial-coverage rule the covered assertion was kept (valid ISO 8601 UTC, equal to the named instant) and the uncovered rendering assertion removed.
- `test_15_errors.py::_gated_env` — the shared setup called `validate_success(...)` with the default 200 on `POST /selection-appointments/{id}/exercise`, which creates a space contract and therefore answers 201 (the reading `test_11` and `test_17` already use). Three tests failed in setup on this. Fixed to `201`, and `test_an_exercised_appointment_refuses_the_replay_before_counting_contracts` now asserts the created contract is `OFFERED` and reads the appointment separately for `EXERCISED`.
- `test_15_errors.py::test_a_delivered_obligation_refuses_the_replay_and_credits_four_points_once` — replayed the resolve as a `FloorManager` with `disposition: WAIVED`. PRD §2.1 answers exactly that with `ERR_ROLE_NOT_PERMITTED`, and §2.11 puts role authorisation (2) ahead of obligation-already-resolved (5), so the request could never reach the gate under test. Re-issued as a second `ShowDirector` (`u_sd_2`), preserving the "different operator, different disposition" narrative.

### Fixes to `test_helpers/`
None — no fixture, factory or role-header helper was at fault.

### Fixes to `implementation/`
- `routes/shows.py::transition_show` — the `SPACE_SELECTION → SELLING` branch set the status but never ran the sweep PRD §3.4 requires ("On success, every appointment of the show still in state `SCHEDULED` transitions to `EXPIRED` with no penalty"). Added the sweep, walked in `created_at` ascending order, bumping each swept appointment's `version`.
- `routes/registrations.py::screen_registration`, `routes/floor.py::adjudicate_violation`, `routes/sponsorship.py::resolve_obligation` — all three read their justification field with `validate.text(..., min_len=1, required=False)`, so an **empty-string** `reason` / `waiver_reason` / `note` was intercepted as `ERR_VALIDATION` at §2.11 priority 1. The PRD pins the empty case to `ERR_WAIVER_REASON_REQUIRED` in all three places ("a mandatory non-empty `reason`", "a present, non-empty `waiver_reason`", "the `note` must be present and non-empty, else `ERR_WAIVER_REASON_REQUIRED`"). Relaxed `min_len` to 0 so the request reaches the priority-9 check; §2.11 step 1 lists no arbitrary string-length rule.

No implementation check required by the PRD was removed or weakened, no endpoint / field / side effect was added that does not trace to PRD prose, and storage remains in-memory only.

## Step 7: Run Tests and Iterate — orchestrator record (verbatim subagent summary) — 2026-09-03T15:12:00.000Z

(The fix subagent self-wrote the entry above; this is the orchestrator's verbatim paste of its returned exit summary, per the skill's worklog contract. Orchestrator independently verified the artifacts: all 8 of `workspace/implementation/results.{1..8}.json` exist and each reports `119 / 119`, and `test_suite/` still contains 119 test functions.)

Loop complete — exit condition met.

## Summary

**Iterations run: 2**
- Iteration 1: **110/119** in all 8 rounds — 9 failures, byte-identical set in every round (no flakiness, no load-induced timeouts, no sweep-reaping signature; both sweeps ran under `setsid nohup` with all 8 rounds concurrent and joined by `wait`).
- Iteration 2: **119/119 in all 8 rounds** (`workspace/implementation/results.1.json` … `results.8.json`, each `passed 119 / total 119 / failed 0 / errors 0`).

**Tests deleted: none.** Every failing assertion traced to a full verbatim PRD sentence, so no STEP 1a silence and no STEP 1b collapse warranted a deletion. One assertion was *split* under STEP 1c rather than deleted:
- `test_suite/test_10_entities.py::test_a_recorded_scan_can_only_ever_be_re_read` — the byte-exact `scanned_at` echo (`...10:05:00Z` vs `...10:05:00.000Z`) is not uniquely derivable: PRD §2.4 both lists `scanned_at` among the timestamps the system writes *and* pins the canonical rendering at three fractional digits, so echoing the client's rendering and restating it canonically are both PRD-faithful. Kept the covered half (valid ISO 8601 UTC + equal to the named instant, compared after parsing); removed only the rendering assertion. Scaffold driver: the lead-scan immutable-entity recipe.

**Fixes to `test_helpers/`: none.** No fixture, factory, or role-header helper was at fault; all test-side defects lived in `test_suite/`.

**Fixes to `test_suite/`** (all STEP 2 "test is wrong" verdicts):
- `test_suite/test_15_errors.py` — `_gated_env` shared setup called `validate_success(client.exercise_appointment(...))` with the default 200; exercising creates a space contract, and PRD §4 says creates answer 201 (as `test_11` and `test_17` already assert). Passed `201`. This single line was aborting setup for 3 tests.
- same file, `test_an_exercised_appointment_refuses_the_replay_before_counting_contracts` — read `env["exercised"]["state"]` off a space-contract body, which has `status`, not `state`. Now asserts the contract is `OFFERED` and reads the appointment separately for `EXERCISED`.
- same file, `test_a_delivered_obligation_refuses_the_replay_and_credits_four_points_once` — replayed the resolve as a `FloorManager` `WAIVED`, which PRD §2.1 answers with `ERR_ROLE_NOT_PERMITTED` at ladder level 2, pre-empting the level-5 `ERR_OBLIGATION_ALREADY_RESOLVED` gate under test. Re-issued from a second `ShowDirector` (`u_sd_2`), preserving the "different operator, different disposition" intent. (This failure was masked by the setup abort in iteration 1's first read.)
- `test_suite/test_02_combinatorial_formula.py::test_thousand_sqft_contract_prices_both_lines_at_the_volume_tier` — arithmetic error: expected `invoice_total_cents == space_fee_cents` and `bundle_discount_pct == 0`, ignoring that PRD §3.5 selects the bundle tier from the **pre-discount** subtotal and 4,269,257 cents clears the two-million band with zero sponsorship attached. Corrected to `bundle_discount_pct 2.5`, `bundle_discount_cents 106731`, `invoice_total_cents 4162526`, plus an explicit `sponsorship_attached_cents == 0`. Hand-verified with Decimal `ROUND_HALF_UP`; the implementation's pricing was already right.
- `test_suite/test_10_entities.py::test_a_planning_edition_reads_back_with_a_zeroed_area_ledger` and `test_suite/test_11_state_machines.py::test_a_floor_plan_with_no_booths_cannot_be_published` — both asserted `net_sellable_sqft is None`, contradicting the PRD sentence each one quotes ("every area and money ledger — `net_sellable_sqft`, … — initialised to zero, with `advance_order_deadline` unset until the floor plan is published"). Changed to `== 0`; the adjacent `advance_order_deadline is None` assertions were correct and left intact.

**Fixes to `implementation/`:**
- `workspace/implementation/routes/shows.py::transition_show` — the `SPACE_SELECTION → SELLING` branch set the status but omitted PRD §3.4's sweep entirely ("every appointment of the show still in state `SCHEDULED` transitions to `EXPIRED` with no penalty"). Added the sweep in `created_at` ascending order, bumping each swept appointment's `version`.
- `workspace/implementation/routes/registrations.py::screen_registration`, `workspace/implementation/routes/floor.py::adjudicate_violation`, `workspace/implementation/routes/sponsorship.py::resolve_obligation` — one logical bug at three parallel sites: each read its justification field with `validate.text(..., min_len=1, required=False)`, so an **empty-string** `reason` / `waiver_reason` / `note` was intercepted as `ERR_VALIDATION` at §2.11 priority 1. PRD pins the empty case to `ERR_WAIVER_REASON_REQUIRED` in all three places, and §2.11 step 1 lists no arbitrary string-length rule. Relaxed `min_len` to 0 so the request reaches the priority-9 check.

No PRD-required implementation check was removed or weakened, no endpoint/field/side effect/header was added without a verbatim PRD sentence behind it, and storage remains in-memory dicts only (no SQLite, no file or `/tmp` persistence, no startup seeding). `pyflakes test_suite/*.py` is clean. All debug artifacts removed — `workspace/` holds only `INSTRUCTION.md`, `PRD.md`, `implementation/`.

## Step 8: Finalize PRD — 2026-09-03T15:20:00.000Z

Step 8 ran (not skipped: Step 7 applied 4 `implementation/` fixes across `routes/shows.py`, `routes/registrations.py`, `routes/floor.py`, `routes/sponsorship.py`).

Done.

## Line counts
- `PRD.md`: 475 lines — `PRD_FINALIZED.md`: 475 lines — **0.0% line delta** (2 lines revised in place, no lines added or removed, no new sections).

## Changes

- **§2.4 (Resource Identity, Timestamps, Versions and the Logical Clock)** — *revise* — Split the single "the timestamps the system writes from it — `executed_at`, `signed_at`, `ordered_at` and `scanned_at` — are recorded from the logical clock" clause into (a) which of those instants actually come from the clock (`executed_at`, `signed_at`, and `ordered_at` only when the request omits it) versus which are the instant the request named (`scanned_at`; `ordered_at` when supplied), and (b) an explicit pin that a client-supplied instant that the system stores (`scanned_at`, `ordered_at`, `window_start`, `window_end`) is normalised to UTC and re-rendered in the canonical three-fractional-digit `Z` form rather than echoed byte-for-byte, while a client-supplied *date* field is stored as a plain ISO 8601 calendar date — `implementation/db.py:70` (`fmt_dt`), `implementation/routes/floor.py:209`, `implementation/routes/floor.py:62`, `implementation/routes/appointments.py:55`.
- **§3.4 (Space Selection Day), exercise paragraph** — *insert* — One sentence pinning that a successful exercise answers HTTP 201 and returns the newly created space contract, not the exercised appointment, in `data` — `implementation/routes/appointments.py:141`.

## Per-edit pre-edit search log

**Edit 1 — subject: how the system renders/derives a stored timestamp, in particular a client-supplied one.**
(b) Paths enumerated: grepped every use of `datetime_field`, `date_field`, `fmt_dt(`, `fmt_date(` across the whole implementation. Read `db.py:70-113` (`fmt_dt` forces `astimezone(utc)` + exactly 3 fractional digits + `Z`; `fmt_date` emits bare `YYYY-MM-DD`; `parse_dt` treats a naive value as UTC), `routes/floor.py:178/209` (`scanned_at`, required, always re-rendered), `routes/floor.py:26/38-39/62` (`ordered_at`, optional, falls back to `now()`), `routes/appointments.py:23-24/55-56` (`window_start`/`window_end`, both re-rendered — and later re-parsed by `parse_dt` at exercise time and in `services.advance_selection_round`), `routes/clock.py:15` (`current_utc` is not persisted on any row), `routes/venue_contracts.py:84` (`executed_at` = `fmt_dt(now())`), `routes/contracts.py:200` (`signed_at` = `fmt_dt(now())`), `db.py:119-144` (`created_at`/`updated_at` = `fmt_dt(now())`), `response.py:16` (`api_request_timestamp`), plus the client-supplied *date* paths `routes/shows.py:37-40/89-92`, `routes/venue_contracts.py:93` → `services.py:215`, and the server-derived dates `routes/shows.py:135` and `services.py:137`.
(c) Wording adjustments made: (i) restricted the canonical-rendering claim to *instants*, and named the four fields exhaustively, so the sentence cannot be read to cover `move_in_start`/`event_start`/`event_end`/`move_out_end`/`terminated_effective_date`, which the impl stores as bare dates; (ii) added the trailing clause explicitly stating the date-field behaviour so the enumerated date paths stay described correctly; (iii) said "records on business rows" rather than "writes", so `api_request_timestamp` and the non-persisted `current_utc` are not swept in; (iv) kept `ordered_at` deliberately two-sided ("from the clock whenever the request omits it… the instant the request named when it does supply it") to match the `if ordered_at is None: ordered_at = now()` fallback rather than picking one source.

**Edit 2 — subject: the HTTP status and `data` payload of an operation that simultaneously transitions an existing row and creates a new one.**
(b) Paths enumerated: grepped every `return created(` / `return object_response(` in `routes/`, and read `response.py:20-30` (`created` = `object_response(data, 201)`). The 201 set is `POST /venue-contracts`, `/shows`, `/shows/{id}/booths`, `/exhibitors`, `/shows/{id}/selection-appointments`, `/selection-appointments/{id}/exercise` (→ `space_contract_view`), `/space-contracts`, `/space-contracts/{id}/rebook` (→ `space_contract_view` of the *fresh* contract, `routes/contracts.py:297`), `/space-contracts/{id}/service-orders`, `/space-contracts/{id}/rule-violations`, `/space-contracts/{id}/lead-scans`, `/shows/{id}/sponsorship-packages`, `/sponsorship-packages/{id}/deals`, `/shows/{id}/registrations`; everything else answers 200, including `POST /booths/{id}/combine` (returns the surviving booth), `publish-floor-plan`, `transition`, `advance-selection-round`, `adjudicate`, `resolve`, `sign`, `cancel`, and `_clock/set_current_utc` (empty object).
(c) Wording adjustment made: scoped the sentence to the exercise endpoint alone and phrased it as a consequence of §4's existing "creates a new resource → 201" rule rather than as a new general principle, so the parallel rebook path (also 201 + new contract) and the 200-answering combine/publish/transition/adjudicate/resolve paths are neither contradicted nor re-legislated.

**Items in `<step_7_diff>` that needed no PRD edit** (PRD already uniquely determines them; the diff was a test bug or an impl-side bug fixed *toward* the PRD): the `_gated_env` 201 argument and the `state`-vs-`status` read (both subsumed by Edit 2's underlying silence); the `FloorManager WAIVED` replay pre-emption (§2.1 + §2.11 step 2 before step 4, and `routes/sponsorship.py:216-217` checks the role before existence); the 1,000-sqft bundle-tier arithmetic (§3.5 already pins pre-discount tier selection, and `calc.py:323-332` matches); `net_sellable_sqft == 0` on a `PLANNING` edition (§3.1 already lists it among the zero-initialised ledgers); the `SPACE_SELECTION → SELLING` appointment sweep (§3.4 sentence verbatim, ordering covered by §2.10); and the `min_len` relaxation on `reason`/`waiver_reason`/`note` (§3.7/§3.8/§3.9 each already pin absent-or-empty to `ERR_WAIVER_REASON_REQUIRED`, and §2.11 step 1 lists no string-length rule for them).

**Orchestrator verification:** `diff PRD.md PRD_FINALIZED.md` reports 8 diff lines / 2 changed line-pairs (lines 84 and 229) — a real non-empty minimal patch, both files 475 lines.

## Step 9: Complete PRD — 2026-09-03T16:05:00.000Z

**Orchestrator decision (recorded per AUTONOMY):** Step 9 was run as **three sequential file-partitioned passes** over `implementation/` rather than one subagent. Rationale: a single agent scanning a 3,630-line implementation against a 475-line PRD reliably runs out of working attention and returns a PRD_COMPLETED.md byte-identical to its input (i.e. the scan silently never ran). Partitioning by implementation layer — pass 1 core/framework, pass 2 formulas/cascades, pass 3 routes — gives each pass a scope it can actually walk exhaustively. Passes were run strictly sequentially (never concurrently) because all three edit the same file; passes 2 and 3 were explicitly told PRD_COMPLETED.md already exists and must be edited in place, never re-copied.

**Total: 68 pins over three passes** (475 lines / 118,082 chars → 477 lines / 138,487 chars; **+20,405 chars**, 54 changed hunks).

### Pass 1 — core/framework (`app.py`, `db.py`, `errors.py`, `guards.py`, `middleware.py`, `response.py`, `validate.py`, `views.py`)
20 pins (16 ambiguity, 4 mismatch). `PRD_FINALIZED.md` 475/118,082 → 475/123,259.
- §2.1 — insert — ambiguity — `X-User-ID` never mandatory; absent ⇒ recorded operator field `null`, and an SoD comparison against `null` never matches — `middleware.py:51`
- §2.1 — insert — ambiguity — `X-Role-Id` empty string is also `ERR_IDENTITY_REQUIRED`; header ignored for the other four roles — `middleware.py:53-58`
- §2.2 — insert — ambiguity — `api_request_id` is `req_` + exactly 20 chars A–Z/0–9 — `db.py:65-67`
- §2.2 — insert — ambiguity — `api_request_timestamp` read from the logical clock, not wall clock — `response.py:13-17`
- §2.2 — revise — mismatch — error envelope covers the 5xx fault too, not only 4xx — `app.py:44-49`
- §2.3 — insert — ambiguity — `offset` unbounded above; non-digit ⇒ `ERR_VALIDATION`; empty string ⇒ default; offset past `total_count` ⇒ empty page, `has_more` false — `response.py:58-83`
- §2.3 — insert — ambiguity — `created_at` ties break by server creation order (no identifier participates) — `db.py:147-152`
- §2.4 — insert — ambiguity — no preloaded data; every collection empty at boot — `db.py:35-39`
- §2.4 — insert — ambiguity — instant parsing accepts `Z`, numeric offset (converted to UTC), or no zone (read as UTC); a date field also accepts a full instant, keeping only the date — `db.py:84-112`
- §2.5 — insert — ambiguity — expected-version field is a required integer ≥ 0; absent/null/non-integer/negative is rung-1 `ERR_VALIDATION`, not a 412 — `validate.py:40-52`, `guards.py:135`
- §2.10 — insert — ambiguity — cascade walks use the same `created_at`+creation-order total order as §2.3 — `db.py:147-152`, `services.py:49,162,200-219`
- §2.11 rung 1 — insert — ambiguity — five request-shape conventions: unparseable/absent/non-JSON body ⇒ empty object; explicit `null` ≡ omitted; integer fields reject booleans and decimal-point numbers; string type-then-length-then-pattern order; identifier arrays must be distinct non-empty strings and an optional array may not be `[]` — `validate.py:21-135`
- §2.11 rung 1 — revise — mismatch — the "every percentage must be an integer" blanket now exempts a cancellation-fee bucket's `pct` — `validate.py:200`
- §3.1 — revise — mismatch — bucket `pct` is a *number* (fractional accepted, stored as supplied), and a stored bucket carries exactly `min_days_out`/`pct`, extra keys discarded — `validate.py:184-207`
- §3.3 — insert — ambiguity — `contact_email` max 254 chars — `validate.py:109`
- §3.5 — insert — ambiguity — `requested_sqft` and `premium_placement_requested` retained/published on the contract, never rewritten by a later leg — `views.py:135,139`
- §3.8 — insert — ambiguity — registration `email` max 254 chars — `validate.py:109`
- §3.8 — insert — ambiguity — lead scan publishes exactly five fields (`id`, `space_contract_id`, `registration_id`, `scanned_at`, `created_at`) — `views.py:275-282`
- §4 — insert — ambiguity — trailing slash served identically, not redirected/refused — `app.py:16`
- §5 — insert — mismatch — three identifiers outside the catalogue: `ERR_NOT_FOUND` 404 (unrouted path), `ERR_METHOD_NOT_ALLOWED` 405 (outranks all of §2.11 including auth), `ERR_INTERNAL` 500 — `app.py:28-49`

Already fully covered, no edits: `errors.py` (machine-verified — all 66 `HTTP_STATUS` entries match the §5 table exactly, zero PRD-only and zero impl-only ids); `guards.py` (every existence/state/OCC/party/floor helper already pinned by §2.11 rungs 4–9 and §3.x); 12 of 14 `views.py` serializers.

### Pass 2 — formulas and cascades (`calc.py`, `services.py`)
11 pins (8 ambiguity, 3 mismatch). 123,259 → 127,651 chars (+4,392).
- §2.6 — insert — ambiguity — `volume_tier_pct`/`bundle_discount_pct` published as JSON integers when whole (`0`, not `0.0`); only the 2.5 band carries a decimal point — `calc.py:108-116,317,330`
- §2.8 — insert — ambiguity — `upheld_violation_count` counts UPHELD citations against *any* space contract of the show whatever that contract's status has since become, so a citation upheld against a since-cancelled contract still counts toward the freeze — `calc.py:213-216`
- §2.9 — revise — mismatch — the "purely additive / equals the summed contributors" equality is broken by reinstatement, which zeroes the counter without revisiting its contributors — `services.py:7-13`, `routes/exhibitors.py:74`
- §2.10 — revise — mismatch — "Aggregates are never lazily derived at read time" is false (every show/deal/package/registration ledger figure is derived live in `views.py` from `calc`); replaced with an observable-freshness statement, and the version-bump rule scoped to the rows each operation names rather than "every ancestor" (impl does *not* bump a venue contract's `version` when a show cancellation moves its `show_count`) — `calc.py:195-239,484-513`
- §3.3 — insert — ambiguity — certified effective footage is `assigned_net_sqft`; the halving falls on the whole contribution including the 5-point rebook bonus and never on footage before block division (worked example added); the certified *spend* term never decays — `calc.py:421-437`
- §3.4 — insert — ambiguity — over-capacity candidates keep `version` unmoved (not merely `rank`/`certified_points_at_rank` null) — `services.py:255-259`
- §3.5 — revise — **mismatch** — signing freezes only the space side (`space_fee_cents`, `volume_tier_pct`, `min_deposit_cents`); the claim that `bundle_discount_pct`/`_cents`/`invoice_total_cents` are "not repriced afterwards" was false, since `NON_TERMINAL_CONTRACT_STATUSES` includes `SIGNED`, so a later sponsorship sign/cancel on the same show *does* rewrite those four figures — `calc.py:91`, `services.py:46-59`, `routes/sponsorship.py:168`
- §3.7 — insert — ambiguity — reprice set is exactly OFFERED/COUNTERED/SIGNED, walked oldest-first, bumping a contract's `version`/`updated_at` **only when one of the four figures actually changed** — `services.py:49-59`
- §3.7 — insert — ambiguity — the `sponsorship_fulfillment_points` reversal is floored at zero, and `fulfillment_credited` stays `true` rather than rewinding — `services.py:117-122`
- §3.9 — insert — ambiguity — the missed-obligation sweep pools every qualifying obligation of the show into one global `created_at` walk (not deal-by-deal), and the 20-point breach charge lands once per deal *after* the sweep, not per obligation — `services.py:175-188`
- §3.9 — revise — **mismatch** — "Cancelled contracts and any scans orphaned with them are excluded from every figure" was a false universal: exclusion holds for `exhibitor_lines`/`total_lead_scans`/the index denominator, but the attendance side counts *any* scan of the registration regardless of the recording contract's status — `calc.py:589-597`, `views.py:268`

Judged already pinned: all of `calc.py`'s constant tables; per-line-then-sum space-fee rounding; the single bundle-discount rounding off the pre-discount subtotal; floor-vs-advance asymmetry; the descending `min_days_out` band scan with negative-days-out zero-bucket fallback; `derived_fulfillment_status`'s five-branch order; `registration_score`'s weight-once-on-the-raw-sum and 60/40 inclusive bands; every empty-set → 0 case; both `max(0, …)` clamps; the two-pass report rounding order; and in `services.py` the cancellation waterfall, cascade=True zero fee, appointment→contract→deal ordering, oldest-first walks, and suspension only from `ACTIVE`.

### Pass 3 — routes layer (all 10 `routes/*.py`), plus final verification
37 changes (19 ambiguity, 18 mismatch), 32 surgical Edits. 127,651 → 138,487 chars (+10,836), +2 lines.
- §2.3 — insert — ambiguity — only declared filters honored; unrecognized query params discarded silently; empty-string filter ≡ omitted; filters exact-match (unknown value → empty page, `total_count` 0), conjunctive, applied before the page window — `routes/sponsorship.py:131-138`, `routes/floor.py:75-78`, `routes/registrations.py:72-75`
- §2.11 rung 1 — insert — ambiguity — unknown request-object keys discarded in silence; body identifiers length-bounded where declared (64 chars for `show_id`, `exhibitor_id`, `target_show_id`, `registration_id`) so an over-long id is `ERR_VALIDATION` not a not-found, while `booth_ids` entries and `venue_contract_id` are unbounded — `routes/shows.py:34`, `routes/sponsorship.py:73`, `routes/floor.py:177`, `routes/contracts.py:252`
- §2.11 rung 4 — revise — mismatch — existence follows the enumerated **entity order**, not "path resources before body references" (exhibitor before package; `booth_ids` before the path appointment/contract), with rebook the sole exception where the path contract precedes `target_show_id` — `routes/sponsorship.py:77-78`, `routes/appointments.py:119`, `routes/contracts.py:264`
- §2.4 — revise — mismatch — `current_utc` mandatory; the clock endpoint answers HTTP 200 with an empty `data` object and echoes nothing — `routes/clock.py:15-18`
- §2.9 — revise — mismatch — **handed item (b)** — `points_awarded` is a record of what signing awarded, not a live mirror of the contribution (zero while `OFFERED`/`COUNTERED`, written at signing as whole blocks only, so a rebooked contract sits exactly 5 points below §3.3's contribution, zero again once `CANCELLED`) — `routes/contracts.py:202`
- §3.1 — revise — mismatch — `gross_sqft` overrun is `ERR_VALIDATION`; both hall comparisons run after the agreement's existence/EXECUTED gates, aisle ratio first — `routes/shows.py:47-54`
- §3.1 — insert — ambiguity — execute reads no body field; its schedule re-verification failure would be a structural `ERR_VALIDATION` (unreachable) — `routes/venue_contracts.py:76-88`
- §3.1 — insert — ambiguity — terminate's `reason` optional 1–500 chars, recorded but never published — `routes/venue_contracts.py:94`
- §3.2 — revise — mismatch — merged survivor also yields `ERR_BOOTH_MERGED`; `ERR_INVALID_COMBINE_SET` reserved solely for a `booth_ids` array containing the survivor; a same-show unmerged child that is `HELD`/`ASSIGNED` or already has a parent → `ERR_BOOTH_NOT_AVAILABLE` — `routes/booths.py:104-110`
- §3.2 — revise — mismatch — combine answers HTTP 200 with the surviving booth — `routes/booths.py:120`
- §3.3 — revise — mismatch — `legal_name` collision is `ERR_VALIDATION`, decided after role authorisation — `routes/exhibitors.py:24-27`
- §3.3 — insert — ambiguity — `points_delta` any unbounded signed integer, `reason` 1–500 recorded-not-published, no standing gate, `status` never changes, negative deltas hitting the zero clamp still succeed — `routes/exhibitors.py:53-60`
- §3.3 — insert — ambiguity — reinstate has no `status` precondition (re-reinstating an `ACTIVE` account succeeds) and its `reason` is not published — `routes/exhibitors.py:66-75`
- §3.4 — insert — ambiguity — booking has no show-status gate (any status incl. `PLANNING`/`CLOSED`), only the exhibitor standing gate; writes the appointment row alone (show `version` unmoved); returns 201 — `routes/appointments.py:19-60`
- §3.4 — insert — ambiguity — `round_index` is the only numerically compared list filter and must be digits (optional single minus) or `ERR_VALIDATION` — `routes/appointments.py:81-86`
- §3.4 — revise — mismatch — exercise requires the edition still `SPACE_SELECTION` (`ERR_INVALID_SHOW_STATUS`), decided before appointment state — `routes/appointments.py:106-107`
- §3.4 — revise — mismatch — `ERR_APPOINTMENT_EXHIBITOR_MISMATCH` fires only for a named booth on another edition's floor; the acting party is policed by `ERR_EXHIBITOR_SCOPE_VIOLATION`, and a `SalesRep` is never refused on that ground — `routes/appointments.py:101,117`
- §3.5 — insert — ambiguity — `requested_sqft` stays mandatory even with explicit `booth_ids` and is never compared to the named booths' area — `routes/contracts.py:25,42-49`
- §3.5 — revise — mismatch — `requested_discount_pct` defaults to 0 and a **counter may itself carry `booth_ids`**, replacing the set, repricing, and bumping the show; a counter without a set change moves nothing but the contract — `routes/contracts.py:78-79,130-149`
- §3.5 — insert — ambiguity — `approved_discount_pct` optional default 0; >100 is rung-1 `ERR_VALIDATION`; 41–100 reaches the cap rule — `routes/contracts.py:81-82,121-125`
- §3.5 — revise — mismatch — a re-offer reprices and bumps both `version`s whether or not `booth_ids` was supplied — `routes/contracts.py:146-152`
- §3.5 — revise — mismatch — sign's booth failures (empty set, unresolvable id, released/reassigned booth) are all `ERR_BOOTH_NOT_AVAILABLE`, after standing and before both money checks — `routes/contracts.py:178-192`
- §3.6 — insert — ambiguity — `amount_cents` must be ≥ 1 (zero is `ERR_VALIDATION`); gates on contract status alone, ignoring show status and floor posture — `routes/contracts.py:212-221`
- §3.7 — insert — ambiguity — `package_code` collision is `ERR_VALIDATION` after the show gates; `price_floor_cents` > list price is `ERR_VALIDATION` at rung 1, pre-authorisation — `routes/sponsorship.py:32-41`
- §3.7 — insert — ambiguity — proposing imposes no show-status requirement (`ON_SITE`/`CLOSED`/`CANCELLED` editions still take proposals) — `routes/sponsorship.py:76-79`
- §3.7 — revise — mismatch — cancelling a `SIGNED` deal on a `CLOSED` show is `ERR_INVALID_SHOW_STATUS`, decided before deal status — `routes/sponsorship.py:185-188`
- §3.7 — insert — ambiguity — resolve's `note` optional under `DELIVERED` and stored null when omitted; the response is HTTP 200 carrying the **obligation**, not the deal — `routes/sponsorship.py:213,229,233`
- §3.8 — revise — mismatch — duplicate `email` is `ERR_VALIDATION`, decided after show existence and status — `routes/registrations.py:32-37`
- §3.8 — revise — mismatch — screening a non-`WAITLISTED` registration is `ERR_VALIDATION` (not a state-conflict code), after the show gate and before `ERR_WAIVER_REASON_REQUIRED` — `routes/registrations.py:90-95`
- §3.9 — revise — mismatch/ambiguity — **handed item (a)** — `notes` optional (1–500, null when omitted); `measured_value` is a number ≥ 0 that need not be whole, mandatory only for `BOOTH_HEIGHT`; for every other type "no rule consults it but the figure supplied is nonetheless stored and published rather than discarded"; the height comparison is against the **lowest** `max_height_ft` among the contract's held-or-assigned booths, and a citation against a contract holding no booth is also `ERR_BOOTH_HEIGHT_LIMIT` — `routes/floor.py:86-89,98-104,110`
- §3.9 — insert — ambiguity — `target_status` accepts exactly `SELLING`/`ON_SITE`/`CLOSED`/`CANCELLED`; anything else (including `PLANNING`, `SPACE_SELECTION`) is rung-1 `ERR_VALIDATION`, while an unreachable member is rung-5 `ERR_INVALID_SHOW_TRANSITION`; `cancellation_reason` accepted and discarded on the other three branches — `routes/shows.py:144-174`
- §3.9 — insert — ambiguity — a service order bumps neither the contract's nor the show's `version` — `routes/floor.py:52-66`
- §3.9 — revise — mismatch — an `UPHELD` disposition discards a supplied `waiver_reason`, leaving it null — `routes/floor.py:141,159-166`
- §3.9 — insert — ambiguity — rebook leaves the source contract `CLOSED_OUT` with its own and its edition's `version` unmoved, and answers 201 with the new target-edition contract — `routes/contracts.py:250-300`
- §4 — revise ×2 — mismatch — added `FloorManager` to the authorized roles of `GET /selection-appointments/{id}` and `GET /selection-appointments` — `routes/appointments.py:67,74`

**Handed-off items resolved.** (a) `routes/floor.py:110`: resolved by revising §3.9 rather than weakening it — `measured_value` remains consulted only for `BOOTH_HEIGHT`, but the PRD now states plainly that a value supplied on any other citation type is stored and published rather than discarded; the old "is ignored for every other type" wording is gone and nothing in §2.11 or the citation error set changed. (b) `routes/contracts.py:202`: resolved by restating §2.9's per-contract clause as a *record written at signing* (whole blocks only) instead of a live mirror; §3.3's 5-point rebook bonus and §3.5's pricing rules are untouched and now consistent.

### Final verification (pass 3, re-confirmed independently by the orchestrator)
- Heading set and order **identical** to `PRD_FINALIZED.md` (`diff` of all `^#` lines is empty).
- No truncation — ends at a real boundary, the last row of the §5 error table (`ERR_DEPOSIT_EXCEEDS_INVOICE | 422`).
- §5 catalogue: **66 of 66** error identifiers present. The three extra `ERR_*` strings (`ERR_NOT_FOUND`, `ERR_METHOD_NOT_ALLOWED`, `ERR_INTERNAL`) are pass 1's framework-level pin, documented in §5 prose as sitting outside the table.
- `diff PRD_FINALIZED.md PRD_COMPLETED.md` → **54 changed hunks**; the scan demonstrably ran (the file is not byte-identical to its input).
- **Green sweep still valid:** every file under `implementation/` and `routes/` has an mtime at or before 13:59:49, while `results.1.json` is 14:06:14 — Steps 8 and 9 modified only `workspace/PRD_*.md` and touched no code, so the recorded 8×119/119 sweep still describes the shipped implementation.

## Pipeline complete
`workspace/PRD_COMPLETED.md` written. Final state: SCAFFOLD.yaml + both design indices; 119 tests in `test_suite/` (zero deleted) over `test_helpers/`; a 3,630-line Flask implementation passing 119/119 in all 8 concurrent rounds; PRD.md → PRD_FINALIZED.md (2 pins) → PRD_COMPLETED.md (68 pins).
