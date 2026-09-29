# Worklog — task_2738_loyalty_liability_breakage_accounting

## Step 1: Create task directory — 2026-09-04T13:55:00.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2738_loyalty_liability_breakage_accounting` and its `workspace/` subdirectory. Index 2738 was pre-assigned by the orchestrating prompt; no scan of `./tasks/` was performed (concurrent pipelines on this host).

## Step 2: Generate scaffold — 2026-09-04T16:10:30.000Z

Scaffold generation for task 2738 is complete and lint-clean.

## Files on disk

`/home/ubuntu/github/CodingPRD/tasks/task_2738_loyalty_liability_breakage_accounting/`

| File | Lines | Bytes | Top-level keys |
|---|---|---|---|
| `SCAFFOLD.yaml` | 3181 | 170261 | `scenario, domain_name, api_prefix, complexity_profile, response_envelope, entities, state_machines, concurrency_rules, calculations, validations, endpoints, errors, roles` (no design keys) |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 1972 | 148711 | `scaffold_difficulty_design` only |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 4739 | 356258 | `scaffold_corner_design` only |

Total 9892 lines.

## Lint verdict (verbatim)

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           /home/ubuntu/github/CodingPRD/tasks/task_2738_loyalty_liability_breakage_accounting/SCAFFOLD.yaml
  Difficulty design:  /home/ubuntu/github/CodingPRD/tasks/task_2738_loyalty_liability_breakage_accounting/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      /home/ubuntu/github/CodingPRD/tasks/task_2738_loyalty_liability_breakage_accounting/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    59
  §1.1 entities declared:     12
  §1.8 instances scanned:     19
  §1.9 instances scanned:     67
  Calls scanned (§1.8+§1.9):  1118

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## Content shape

- §1.0–§1.7: 12 entities (graph topology), 10 state machines (cyclic), 2 OCC concurrency rules, 8 calculations, 38 validations on a strict priority ladder, 60 declared endpoints (59 distinct after template collapsing), 49 error codes, 5 roles under segregation of duties. Money in integer cents, `*_millicents_per_point` for SSP, rates in basis points, `round_half_up`, logical clock `2026-08-01T00:00:00Z`, `api_prefix: ""`.
- §1.8: all nine `rule_id`s present with 19 instances (`combinatorial_formula` has 3, the rest 2 each).
- §1.9: 89 instances across all nine required sections — 67 with full `test_recipe`, 22 `excluded_because` stubs. Sections: entities 15, state_machines 19, calculations 14, validations 13, endpoints 6, errors 5, rbac 7, cross_cutting 8, consistency_model 2.

## Post-lint audit fixes applied this session

The lint doesn't cover everything the spec requires, so I ran an independent checker. Three issues found and fixed:

1. **Inconsistent `excluded_because.difficulty_instance` format** — 12 of the 22 stubs cited the bare instance name while 10 used the spec's `rule_id / instance_name` form (SKILL.md:703). Normalized all 22 to the prefixed form; every cited target now resolves to a real §1.8 instance *and* its rule_id matches.
2. **Forbidden concurrency vocabulary** — `SCAFFOLD_DIFFICULTY_DESIGN.yaml:1453` used "simultaneously" (describing a cascade side effect, not a race). Reworded to "that same operation also settles...".
3. Removed a stray whitespace-only line in the corner design (4740 → 4739 lines).

Also verified clean: name uniqueness across the union of both design files, no stub carrying a `test_recipe`, every full instance having `distinguishing_aspect`, and every `expected_*_version` payload value being a `${...}` placeholder rather than a bare literal.

The hard constraint was honored throughout — no sibling task under `tasks/` was listed, globbed, grepped, or read.

## Step 3: Copy shared files — 2026-09-04T16:11:20.000Z

Copied `./INSTRUCTION.md` to `tasks/task_2738_loyalty_liability_breakage_accounting/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-04T16:47:00.000Z

PRD generation complete.

## Output
`/home/ubuntu/github/CodingPRD/tasks/task_2738_loyalty_liability_breakage_accounting/workspace/PRD.md` — **510 lines**, built incrementally via `Write` + five `cat >> … <<'PRDEOF'` heredoc appends (no single giant write). The file ends at a true section boundary: the final row of the §5 error table (`| \`ERR_PROGRAM_CONFIG_INCOMPLETE\` | 409 |`), not mid-sentence.

Structure: §1 Introduction; §2.1–§2.10 (RBAC, verbatim response envelope, pagination, logical clock, money/rounding, identity & derived reads, OCC, a 37-rung validation ladder with both engineered conflict pairs, cascade discipline, bounded cycles); §3.1–§3.9 (programme setup, accounting calendar, issuance, redemption/allocation/fulfilment/reversal, partner settlement & dispute cycle, breakage estimation & approval, the eight-step close rollforward, expiry/escheat/dormancy, programme change orders); §4 endpoint table (59 rows); §5 error catalogue (49 rows).

## Hard Contract reports

**Contract 1 — Field-Name Coverage: PASS.** Verified mechanically: all **144** `entities[].fields[].name` identifiers and all **72** distinct `input:` identifiers (request bodies + query params, `?` stripped) from the scaffold appear verbatim in backticks in PRD.md — zero missing. The four common audit fields (`id`, `created_at`, `updated_at`, `version`) are present, including the note that `RedemptionAllocation` carries only `id` and `created_at`. Path params are only `{id}`.

**Contract 2 — Rule Coverage: PASS.** All 46 state-machine transitions are narrated with their preconditions and side effects, including the system-triggered ones (lot `EXPIRED → ESCHEATED`, member `ACTIVE → DORMANT`, estimate `APPROVED → SUPERSEDED`, statement `DRAFT → SUPERSEDED`, agreement `ACTIVE → SUSPENDED` on write-off, order `MODELED → CANCELLED`, and the forced `SOFT_CLOSED → OPEN` reopen that is exempt from the `reopen_count` gate but still consumes it). All 8 calculations are covered with their order-sensitivity made normative in prose (two separate issuance roundings; per-line reserve deduction; clamp-per-cohort-before-weighting; read-before-zeroing on expiry; threshold after carry-forward; independently rounded projection legs; independently rounded sensitivity bands; the eight pinned rollforward steps with at-close vs at-estimate gross). Both OCC rules, all 37 validation rungs with `applies_to` scopes expressed as action names, both deliberate priority conflicts, all field-level defaults/ranges, and both GROSS/NET and all three estimate variants written at equal density.

**Contract 3 — §3 Path Purity: PASS.** Scripted check over §3: zero backticked tokens beginning with `/`, zero bare HTTP-method tokens, zero method+path combinations, and zero raw slash-paths outside backticks. §2 is likewise path-free. Endpoints in §3 are referred to only by state-transition framing, role + action verb, or capability description. Paths appear only in the §4 table.

**Style/fidelity checks:** no pseudocode operators (`==`, `>=`, `+=`, `round_half_up(`, `clamp(`, `SUM(`, `floor(` all absent), no fuzzy quantifiers (`approximately`/`roughly`/`conservatively` absent), §2.2 pasted byte-verbatim from the skill file.

## Scaffold issue to flag

1. **`AccountingPeriod.breakage_recognized_cents` is defined two different ways.** §1.1 (SCAFFOLD.yaml:375) says `expiry_released_cents - catch_up_adjustment_cents`; §1.3 `period_close_rollforward` STEP 8 (SCAFFOLD.yaml:1831) says `-1 * catch_up_adjustment_cents`. The worked figures cannot discriminate because `expiry_released_cents` is 0 in the canonical fixture. **I followed the §1.3 calculations table** (negation of the catch-up), on the grounds that §1.3 is the authoritative formula surface. If the hidden test suite was generated from the §1.1 wording instead, any fixture with a non-zero `expiry_released_cents` at close will diverge — worth reconciling before Step 5.
2. Minor: the same §1.1 block labels `catch_up_adjustment_cents` as "Step 6" and `breakage_recognized_cents` as "Step 8", while §1.3 puts both in STEP 8 and uses STEP 6 for `pre_catchup_liability_cents`. The PRD uses the §1.3 step numbering.

I did not open, grep, or reference `SCAFFOLD_DIFFICULTY_DESIGN.yaml` or `SCAFFOLD_CORNER_DESIGN.yaml`, and did not read or write `worklog.md`.

### Orchestrator note (Step 4 verification)

Tail check performed by the orchestrator: `PRD.md` is 510 lines, top-level headings §1–§5 all present, and the file ends on the last row of the §5 error table. Not truncated; no regeneration required. The flagged `breakage_recognized_cents` divergence is left unresolved by design — the PRD is the contract, so if the design-index-derived tests assert the §1.1 reading, Step 7's PRD-First protocol will adjudicate it there rather than the orchestrator patching the scaffold mid-pipeline.

## Step 5: Generate unit tests — 2026-09-04T17:22:00.000Z

Both stages are complete, on disk at the task root, and fully verified.

## Locations (task root, nothing under `workspace/`)
- `/home/ubuntu/github/CodingPRD/tasks/task_2738_loyalty_liability_breakage_accounting/test_helpers/` — 9 files, **2181 lines**: `__init__.py` 35, `api_client.py` 373, `api_errors.py` 159, `assertions.py` 294, `constants.py` 275, `factories.py` 294, `fixtures.py` 339, `test_users.py` 101, `types.py` 311.
- `/home/ubuntu/github/CodingPRD/tasks/task_2738_loyalty_liability_breakage_accounting/test_suite/` — 19 files, **12209 lines**: `conftest.py` 48; `test_01` 456, `test_02` 585, `test_03` 474, `test_04` 544, `test_05` 370, `test_06` 363, `test_07` 489, `test_08` 503, `test_09` 759, `test_10` 1009, `test_11` 1605, `test_12` 1169, `test_13` 1052, `test_14` 421, `test_15` 456, `test_16` 778, `test_17` 729, `test_18` 399.
- Stray-directory sweep under `workspace/` (excluding the off-limits `implementation/`): nothing found. `workspace/implementation/` was never read or written; `worklog.md` untouched. `__pycache__`/`.pytest_cache` removed.

## Verification results
- **Collection:** `PYTHONPATH=. pytest test_suite/ --collect-only -q` → **213 tests collected, 0 errors** (167 test functions, the rest parametrised cases). `pyflakes` clean across both directories.
- **Design-tag audit:** 167 functions, 167 `Design:` lines — exactly one per test, each the last docstring line, every tag resolving to a real instance, **zero `excluded_because:` stubs translated**.
- **Coverage: complete.** All **19 live difficulty instances** have ≥2 tests; all **67 live corner instances** have ≥1.
- **PRD citations:** every quoted run ≥40 chars in every docstring is a literal substring of `workspace/PRD.md` — **0 problems**. Forbidden-vocabulary scan (scaffold / yaml / design-index / § references) is clean outside the `Design:` lines.

## Helper defects found and fixed during generation
1. `fixtures.active_program()` created a cohort but no `StateExpiryRule`, so every activation through it (and through `issuance_ready` / `partner_issuance_ready`) would have failed `ERR_PROGRAM_CONFIG_INCOMPLETE` (PRD line 217). Added `configured_program()` and threaded `rule_overrides` through. Four subagents flagged this independently and defensively built local `_activated_program()` / `_ledger_ready()` helpers before the fix landed; those remain and are harmless.
2. `constants.ORDER_APPLIED = "APPLIED"` was wrong — PRD lines 384 and 456 pin the terminal change-order state as `EFFECTIVE`. Renamed to `ORDER_EFFECTIVE = "EFFECTIVE"`; verified no module references the old name.
3. Earlier fixes in this workstream: `ERROR_ENVELOPE_FIELDS` no longer carries a non-existent `details`; the invented `COALITION` relationship type removed; `DEFAULT_MIN_INVOICE_CENTS` corrected 1000 → 5000; `assert_rollforward_ties` corrected to *subtract* `remeasurement_delta_cents` per the normative sign order on PRD line 344; `factories` no longer defeats the "pass `None` to omit a field" contract.
4. One docstring in `test_13_validations.py` used an inline quoted word inside prose, which broke literal-grep pairing of the surrounding citations; reworded so all quotes are pure PRD citations.

## Notable PRD-over-scaffold divergences honoured
`breakage_recognized_cents` = −`catch_up_adjustment_cents`; real field is `tier_benefit_expense_cents` (not `tier_expense_cents`); `provisional_release_cents` (not `provisional_revenue_recognized_cents`); `low/base/high_required_liability_cents`; change-order terminal state `EFFECTIVE`; `CO_BRAND` and `SINGLE_COHORT`-as-`breakage_method` are not PRD enum values; one design case used `behavior_elasticity_bp: -9000` outside the PRD's −5000…5000 band and was rebuilt with independently recomputed figures.

## Deliberate skips (gaps left as gaps, per the two-condition filter)
No whole instance was skipped, but four sub-assertions were dropped rather than weakened: unsupported HTTP methods on state-expiry-rules (no PRD status), reopen-after-hard-close ladder order (rung 12 vs 14 genuinely ambiguous), `ERR_INVALID_WINDOW` vs `ERR_PERIOD_OVERLAP` precedence (no well-formed body violates both), and a `point_balance` read whose only defining sentence is not uniquely derivable. Two further scaffold claims were corrected in place rather than asserted: the soft-close ladder ordering (`ERR_ESTIMATE_NOT_APPROVED`/`ERR_UNALLOCATED_REDEMPTIONS` outrank `ERR_PERIOD_NOT_ENDED`) and the historical-rate out-of-band probe (`9801`, not `10001`).

## Step 6: Generate implementation — 2026-09-04T16:35:00.000Z

Implementation complete and verified from a cold boot.

## Location
`/home/ubuntu/github/CodingPRD/tasks/task_2738_loyalty_liability_breakage_accounting/workspace/implementation/`

## Architecture
- **`app.py`** — `create_app()` registers ten blueprints, `strict_slashes = False`, a `before_request`/`teardown_request` pair that holds the single module-level `db.lock` (RLock) for the whole request, handlers for `ApiError`, 404, 405 and a catch-all `Exception`, and `app.run(host="0.0.0.0", port=int(os.environ["PORT"] or 10000), threaded=True, use_reloader=False)`.
- **Shared core** — `util.py` (logical UTC clock pinned at `2026-08-01T00:00:00Z`, `rhu` round-half-up primitive, `add_days`, `whole_days_between`, `iso` with exactly 3 fractional digits), `errors.py` (all 49 codes → status), `db.py` (pure in-memory dicts plus ordering helpers), `response.py` (envelope + pagination), `auth.py` (5 roles, entity-backed identities), `validate.py` (typed field extractors), `calc.py` (all 8 calculations), `serialize.py`, `lookup.py`.
- **Routes** — `clock`, `programs`, `config` (rules/cohorts/members), `periods`, `partner_agreements`, `point_lots`, `redemption_events`, `breakage_estimates`, `settlement_statements`, `change_orders`.
- **`start.sh`** — `cd "$(dirname "$0")"`, guarded `pip install -q -r requirements.txt` only if Flask is missing, `export PORT="${PORT:-10000}"`, `exec python3 app.py`. Storage is in-memory only; nothing is seeded, preloaded or persisted, so every `per-test-server` relaunch starts empty.

## Final inventory (23 files, 2769 lines)
`app.py` 79, `auth.py` 52, `calc.py` 323, `db.py` 131, `errors.py` 74, `lookup.py` 82, `response.py` 88, `serialize.py` 176, `util.py` 99, `validate.py` 166, `requirements.txt` 1, `start.sh` 8, `routes/__init__.py` 1, `routes/breakage_estimates.py` 186, `routes/change_orders.py` 153, `routes/clock.py` 19, `routes/config.py` 158, `routes/partner_agreements.py` 99, `routes/periods.py` 213, `routes/point_lots.py` 106, `routes/programs.py` 118, `routes/redemption_events.py` 241, `routes/settlement_statements.py` 196.

## Verification
Every module parses (`ast.parse` clean). Three smoke scripts exercised the happy path, ~30 negative paths and the partner-economics path; a final cold boot on port 18991 returned `201` with a well-formed envelope (`req_JE4LLUQJDU3GZY2TLZJU`, timestamp `…746Z`, `response_type: "object"`, `status: DRAFT`, `current_breakage_rate_bp: 0`, derived `total_deferred_revenue_cents: 0`) and `?limit=0` correctly returned 400. Both smoke servers were killed by `kill $(lsof -ti tcp:PORT)` — ports 18773 and 18991 are confirmed free, no broad pattern kill was ever used. `__pycache__` removed.

## Spec decisions worth flagging to the reviewer
- Ladder priority governs ordering everywhere: ownership (21) before shape (30) on `POST /redemption-events` since it is computable from the raw body, but path-addressed resources necessarily 404 before 403.
- Cross-programme statement create raises `ERR_PERIOD_PROGRAM_MISMATCH` (rung 80 < 82); reopening a `HARD_CLOSED` period raises `ERR_INVALID_STATE_TRANSITION` (62 < 64); cohort enrollment-window violations are `ERR_INVALID_REQUEST` because rung 75 covers only periods and agreements.
- `REVERSAL` rows reuse the original `allocation_seq` with negated amounts, which is what makes the declared "allocation_seq then created_at" journal ordering meaningful.
- The reopen reset set is exactly the seven persisted rollforward fields, shared as `ROLLFORWARD_PERSISTED` in `routes/periods.py` between manual reopen and the estimate-approval forced reopen.
- Period `version` is not bumped by issuance/allocation/fulfill/reverse; member `version` bumps only on DORMANT→ACTIVE revival. `current_breakage_rate_bp` is seeded only on first DRAFT→ACTIVE activation, never on SUSPENDED reactivation.
- Confirmed against the scaffold that only LoyaltyProgram, Member and PointLot carry DERIVED-ON-READ fields; AccountingPeriod and PartnerAgreement figures are all persisted, matching `serialize.py`.

### Orchestrator note (Steps 5/6 verification)

Steps 5 and 6 ran concurrently as background subagents. Layout verified after both exited: `test_helpers/` (9 files) and `test_suite/` (19 files) at the task root, `workspace/implementation/` (14 entries incl. `routes/`), no stray test directories under `workspace/`. A leftover `workspace/implementation/__pycache__` was removed by the orchestrator. 213 tests collect cleanly.

## Step 7: Run tests and iterate — 2026-09-04T17:47:00.000Z

Clean. Final state: all 8 parallel rounds pass 213/213.

## Summary

**Iterations run:** 2

**Iteration 1** — 8/8 rounds identically at 209/213 (4 deterministic failures, no flakiness):
- `test_02_combinatorial_formulas.py::test_the_measurement_is_frozen_at_creation_and_installs_no_rate` — setup failed `409 ERR_ESTIMATE_NOT_APPROVED`
- `test_06_boundary_precision.py::test_measured_points_exactly_on_the_cap_are_accepted` — "Expected 200, got 201"
- `test_06_boundary_precision.py::test_the_rounded_count_one_point_under_the_cap_is_measured_in_full` — same
- `test_06_boundary_precision.py::test_measured_points_one_point_above_the_cap_are_rejected` — same

**Iteration 2** — 8/8 rounds at 213/213, duration ~390s per round.

**Tests deleted:** none. All four failures passed STEP 1a (PRD verbatim-covers) and STEP 1b (unique derivability), and resolved at STEP 2 as test bugs.

**Fixes applied to `test_helpers/`:** none — no shared fixture/factory/assertion defect. The two bugs lived in the test functions' own call sites, so they were fixed in `test_suite/`.

**Fixes applied to `test_suite/`:**
- `/home/ubuntu/github/CodingPRD/tasks/task_2738_loyalty_liability_breakage_accounting/test_suite/test_06_boundary_precision.py` — three cap-boundary tests wrapped the `POST /point-lots` response in `assert_ok` (which pins HTTP 200) instead of `assert_created`. PRD §4: "Creation endpoints return HTTP 201 with the created resource in `data`." The implementation was correct; the assertion mis-translated the status. Switched all four call sites to `assert_created` (which additionally verifies `version == 1`, also PRD-required), and added the import. This made the tests *more* faithful to PRD — no assertion was weakened, and the full field-by-field measurement assertions are untouched.
- `.../test_suite/test_02_combinatorial_formulas.py` — `test_the_measurement_is_frozen_at_creation_and_installs_no_rate` created only a DRAFT estimate, then called `fixtures.fulfilled_redemption`. PRD §3.4 requires fulfilment to have "an `APPROVED` breakage estimate to exist for that period; without one the attempt is rejected with `ERR_ESTIMATE_NOT_APPROVED`", so the PRD-faithful implementation correctly refused. Approving an estimate was not an option: PRD §3.6 first link says approval "overwrites" `current_breakage_rate_bp`, and this test's final assertion is precisely that the rate is still the activation-seeded 2500 bp. Swapped to `fixtures.allocated_redemption`, which is the step that actually moves the outstanding balance (5266 → 2266 points, 6319 → 2719 cents — the docstring's figures stay exactly right, since PRD states "No lot balance moves at fulfilment"). Every assertion in the test is byte-identical; only the PRD-inconsistent request was corrected, plus a docstring word and an explanatory comment.

**Fixes applied to `implementation/`:** none. No implementation defect was found — both failure classes traced to the test layer, and no PRD-required check was removed or weakened to accommodate them.

### Orchestrator note (Step 7 verification)

Sweep artifacts independently verified by the orchestrator rather than taken on the subagent's word: all eight `workspace/implementation/results.{1..8}.json` exist (timestamped 17:46, ~62 KB each) and each reports `passed=213 / total=213 / failed=0`. Step 8 is NOT skipped — Step 7 ran 2 iterations with two `test_suite/` fixes, so the skip condition (zero iterations beyond baseline) does not hold, even though `implementation/` fix count is 0.

## Step 8: Finalize PRD — 2026-09-04T17:51:00.000Z

## Verdict

`workspace/PRD_FINALIZED.md` was created as a byte-identical copy of `PRD.md` (510 lines each, md5 `d6faf4b163771c449a7dac8ed2c8ebcd`, 0.0% delta). **No edit was warranted.** Both `<step_7_diff>` items were test-layer bugs against behavior the PRD already determines uniquely, and Step 7 itself applied zero implementation fixes and zero deletions.

## Per-item analysis (candidate edits considered, all rejected)

**Item A — three cap-boundary tests wrapped `POST /point-lots` in `assert_ok` (200) instead of `assert_created` (201).**
- (a) Subject: HTTP status and `version` of the point-lot creation response; the inclusive `per_issuance_point_cap` comparison the tests exercise.
- (b) Impl paths enumerated: `implementation/routes/point_lots.py:79` (`return created(...)`), `implementation/response.py:33-34` (`created()` → `ok(data, 201)`), all 11 `created(` call sites across `implementation/routes/*.py` (every creation endpoint is 201, none 200), `implementation/routes/point_lots.py:49-50` (cap test: `points_issued > per_issuance_point_cap` → `ERR_ISSUANCE_CAP_EXCEEDED`, i.e. strictly greater, tested only after measurement), `implementation/calc.py:85-104` (`issuance_measurement`: two separate `rhu` roundings, tier then promo), `implementation/routes/point_lots.py:42-43` (promo cap rung above the issuance cap rung, matching ladder rungs 32 vs 34).
- (c) No wording adjustment, because no edit: PRD §4 line 394 already states "Creation endpoints return HTTP 201 with the created resource in `data`", §2.6 already pins `version` starting at 1 on creation, and §3.3 already pins both the inclusive cap ("a lot whose measured point count lands exactly on the cap is accepted and only a strictly larger count is rejected") and the cap being tested after measurement. The impl matches all of it verbatim; the mis-translation lived solely in the assertion helper choice.

**Item B — `test_the_measurement_is_frozen_at_creation_and_installs_no_rate` called `fulfilled_redemption` with only a DRAFT estimate present.**
- (a) Subject: the fulfilment precondition that an `APPROVED` breakage estimate exists for the event's period, and the (non-)movement of lot balances / programme rate at each redemption stage.
- (b) Impl paths enumerated: `implementation/routes/redemption_events.py:174-179` (fulfil: period `OPEN` → state `ALLOCATED` → `ERR_ESTIMATE_NOT_APPROVED`, ladder order 10/12/17 as §2.8 requires), `implementation/calc.py:200-204` (`approved_estimate_for_period` — matches on `period_id` + `state == "APPROVED"`, exactly as §3.4/§3.7 word it), the other two callers of that helper `implementation/routes/periods.py:99` (soft-close precondition) and `:143` (Step 7 `approved_estimate_rate_bp`) plus `implementation/calc.py:235`, `implementation/routes/redemption_events.py:139-145` (allocation is where `points_remaining` moves) and `:180-195` (fulfilment writes only `final_release_cents`/delta — "No lot balance moves at fulfilment"), and `implementation/routes/breakage_estimates.py` approval path for the rate-install/first-link behavior the test asserts has *not* happened.
- (c) No wording adjustment, because no edit: §3.4 already says fulfilment requires "an `APPROVED` breakage estimate to exist for that period; without one the attempt is rejected with `ERR_ESTIMATE_NOT_APPROVED`", §3.6 already says measurement "runs at creation and is frozen thereafter" and that only approval overwrites `current_breakage_rate_bp`, and §3.1 already pins the activation-seeded 2500 bp. The test simply requested the wrong stage; the implementation was PRD-faithful.

No third-party silence was patched, since Step 9 owns the full PRD-vs-impl scan outside this scope.

### Orchestrator note (Step 8 verification)

A byte-identical `PRD_FINALIZED.md` is the correct outcome here: Step 7 made zero `implementation/` fixes and zero deletions, so there was no PRD-silence signal to patch. Verified on disk — both files are 101652 bytes. Step 9 is next and, unlike Step 8, must NOT come out identical: it runs as three sequential impl-module-partitioned passes over one shared `PRD_COMPLETED.md` (pass 1 does the `cp`, passes 2 and 3 must not).

## Step 9: Complete PRD — 2026-09-04T18:41:00.000Z

Step 9 was executed as **three sequential passes** over one shared `workspace/PRD_COMPLETED.md`, partitioned by implementation module (pass 1 performed the `cp` from `PRD_FINALIZED.md`; passes 2 and 3 edited in place, additively). Verbatim pass summaries follow.

### Pass 1 of 3 — core + programme-setup modules (`app.py`, `response.py`, `errors.py`, `auth.py`, `validate.py`, `util.py`, `db.py`, `lookup.py`, `serialize.py`, `routes/clock.py`, `routes/programs.py`, `routes/config.py`)

**Source vs output:** `PRD_FINALIZED.md` 510 lines / 101,652 chars → `PRD_COMPLETED.md` 511 lines / 111,050 chars (**+1 line, +9,398 chars**). 16 diff hunks; file still ends at the real final boundary (`| ERR_PROGRAM_CONFIG_INCOMPLETE | 409 |`, the last §5 row).

**Counts:** 21 changes — **18 ambiguity-pins**, **3 mismatch-revisions** (2 distinct mismatch subjects, one of which needed patching in two places).

Changes:
- §2.1 — revise — ambiguity — whitespace-only header counts as missing (and empty role is `ERR_MISSING_AUTH_HEADERS`, not `ERR_UNKNOWN_ROLE`); role names matched exactly and case-sensitively — `auth.py:28-31`
- §2.2 — revise — ambiguity — `api_request_id` is `req_` + exactly 20 chars from `A-Z0-9` (24 total) — `response.py:10,18-19`
- §2.2 — revise — **mismatch** — `api_request_timestamp` is drawn from the machine's real clock, not the logical clock — `response.py:25`, `util.py:1-7,76`
- §2.2 — revise — ambiguity — `message` wording is not contractual, only `error_id` + status are — `errors.py:12-62`
- §2.2 — insert (new bullet) — ambiguity — unmatched path → `ERR_INVALID_REQUEST` at **404**, unmatched method → same id at **405**, unhandled failure → same id at 500 — `app.py:57-69`
- §2.3 — revise — ambiguity — non-integer `limit`/`offset` → 400; `offset` has no maximum; empty-string param = absent; `total_count` counted pre-window; `has_more` = `offset + len(returned) < total_count`; single reads omit all four — `response.py:42,60-81`
- §2.3 — insert — ambiguity — `created_at` ties (the norm under a frozen clock) break on internal insertion order, for list reads *and* §2.9 cascade orders; the sequence is not an exposed field — `db.py:78-103`
- §2.3 — insert — ambiguity — filter semantics: empty value ignored, undeclared params ignored, string comparison with no enum/range validation (bad value → empty page, not 400), booleans accept `true/false/1/0` case-insensitively, null values never match — `lookup.py:61-82`
- §2.4 — revise — **mismatch** — "Nothing reads the wall clock" narrowed to domain timestamps, carving out `api_request_timestamp` — `util.py:1-7`
- §2.4 — insert — ambiguity — store is empty at startup, nothing seeded; fresh collection reads give `total_count` 0 — `db.py:21-37`
- §2.4 — insert — ambiguity — `current_utc` required and must parse (else 400); clock may be set backwards (no monotonicity); response is 200 with empty `data` — `routes/clock.py:13-19`
- §2.6 — insert — ambiguity — `updated_at == created_at` at creation; every emitted timestamp is UTC, 3 fractional digits, finer precision **truncated**; absent timestamps emit `null`; offset-bearing inputs normalised to UTC — `util.py:63-73`, `db.py:49-59`
- §2.6 — insert — ambiguity — derived-on-read figures are computed for list rows too, in the same `data` object — `serialize.py:121-156`, `response.py:84-88`
- §2.8 rung 4 — revise — **mismatch** — for the five path-addressed ownership ops the path resolves **first**, so a bad id yields its 404, never `ERR_NOT_RESOURCE_OWNER`; ownership then outranks rungs 5+; redemption request compares the raw body `member_id` before body validation (and an omitted `member_id` from a `Member` is 403) — `config.py:155-157`, `point_lots.py:93-95`, `redemption_events.py:32-35,84-86`, `settlement_statements.py:88-90,118-120`
- §2.8 rung 5 — insert — ambiguity — absent/empty body = `{}`; non-object or invalid JSON fails here; JSON `null` = absent (required fails, optional defaults); `""` is present-but-invalid; undeclared keys ignored; strict types (bool ≠ int, digit-string ≠ int); whitespace-only rejected for non-empty strings; max length counts untrimmed — `validate.py:14-65,121-130`
- §2.9 — insert — ambiguity — requests processed strictly one at a time; all `updated_at` writes in one request share one clock reading — `app.py:39-51`, `db.py:72-75`
- §3.1 — insert — ambiguity — tier-multiplier value range is a rung-5 check over **every key present**, so an out-of-range fifth key gives 400 while an in-range fifth key gives `ERR_TIER_MULTIPLIER_KEYS_INVALID`; non-object or non-integer value → 400 — `validate.py:136-157`, `programs.py:38-39`
- §3.1 — insert — ambiguity — only `escheat_rate_bp` is optional on a StateExpiryRule; the other three inputs are required; rule serializer field set — `config.py:33-37`, `serialize.py:33-36`
- §3.1 — insert — ambiguity — a bad cohort enrolment window is `ERR_INVALID_REQUEST` (400) at rung 5, **not** `ERR_INVALID_WINDOW` (explaining cohort create's absence from rung 19), and precedes FK resolution and duplicate-code — `config.py:81-83`
- §3.1 — insert — ambiguity — a programme with no periods closes without objection; the state check precedes the `ERR_PERIODS_NOT_CLOSED` test — `programs.py:107-116`
- §4 intro — insert — ambiguity — trailing slash insignificant (`strict_slashes = False`) — `app.py:34`

Scope confirmation: scanned exhaustively `app.py`, `response.py`, `errors.py`, `auth.py`, `validate.py`, `util.py`, `db.py`, `lookup.py`, `serialize.py`, `routes/clock.py`, `routes/programs.py`, `routes/config.py`. Read-only cross-checks (no patches) in the other passes' modules. No PRD passage owned by a later pass was patched. Two verifications relayed: all 49 error ids in `errors.py` match §5 exactly (byte-diff clean), and every `ApiError` status at every raise site matches its §5 row — §5 needed no edits. Two notes handed to later passes: (a) §3.2's "all eleven" rollforward figures vs a twelve-item list (11 `_cents` + `approved_estimate_rate_bp`) — wording, not an impl mismatch; (b) §2.4's "In all three cases the end must fall strictly after the start" left unqualified for period and agreement windows, since those two do use `ERR_INVALID_WINDOW` — only the cohort clause needed pinning.

### Pass 2 of 3 — ledger modules (`calc.py`, `routes/periods.py`, `routes/point_lots.py`, `routes/redemption_events.py`)

**File size:** before 511 lines / 111,050 chars → after 511 lines / **117,757 chars**. File still ends at `| ERR_PROGRAM_CONFIG_INCOMPLETE | 409 |`. Pass 1's 21 edits all still present (distinctive strings spot-checked in §2.1, §2.2, §2.3, §3.1, §4 intro — all intact).

**Counts:** 26 edits — **21 ambiguity-pins**, **5 mismatch-revisions**.

Changes:
- §2.8 rung 14 — revise — mismatch — dropped "period reopen" from the `ERR_PERIOD_HARD_CLOSED` rung; that code is unreachable on reopen because rung 12 fires first — `routes/periods.py:129`
- §2.9 (hard-closed immutability para) — revise — mismatch — same correction: only the four statement operations report `ERR_PERIOD_HARD_CLOSED` — `routes/periods.py:129`, `routes/settlement_statements.py:44`
- §3.2 ¶1 — insert — ambiguity — overlap and duplicate-label tests scan siblings in any `state`; period create is not gated on programme `status` — `routes/periods.py:38-47`
- §3.2 ¶2 — revise — ambiguity — "all eleven … figures" → "all twelve … the eleven `_cents` amounts and the one basis-point rate" (pass 1's note (a)) — `routes/periods.py:54-65`
- §3.2 ¶3 — insert — ambiguity — accumulator writes by issuance/allocate/fulfil/reverse do **not** bump the period's `version`/`updated_at`; only the sweep, closes and reopens do — `routes/point_lots.py:70`, `routes/redemption_events.py:160,193,231`
- §3.2 ¶4 — revise — mismatch — reopen of a `HARD_CLOSED` period is `ERR_INVALID_STATE_TRANSITION`, not `ERR_PERIOD_HARD_CLOSED` — `routes/periods.py:129`
- §3.3 (freeze list) — revise — ambiguity — "four values" → "the following values" (five items listed) — `routes/point_lots.py:52-64`
- §3.3 (cap para) — insert — ambiguity — `expired_gross_ssp_cents`/`escheated_cents` born 0; programme resolved from the member; `promo_multiplier_bp` has no shape-rung ceiling, `base_points` no upper bound — `routes/point_lots.py:27-35,61-62`
- §3.3 (member refresh) — insert — ambiguity — the plain `last_activity_at` refresh is not a mutation; only `DORMANT → ACTIVE` bumps the member — `routes/point_lots.py:73-76`
- §3.4 (request) — insert — ambiguity — `PARTNER` without `partner_agreement_id` is `ERR_INVALID_REQUEST` at rung 5, ahead of FK resolution — `routes/redemption_events.py:41-42`
- §3.4 (FIFO candidates) — insert — ambiguity — candidate lot set is not period-scoped — `routes/redemption_events.py:113-116`
- §3.4 (fulfilment) — insert — ambiguity — fulfilment bumps neither lots nor agreement, and does not require an `ACTIVE` programme — `routes/redemption_events.py:169-195`
- §3.4 (reversal intro) — insert — ambiguity — reversal likewise does not require an `ACTIVE` programme — `routes/redemption_events.py:198-208`
- §3.4 (reversal reason) — insert — ambiguity — `reversal_reason` required, non-empty, ≤500 chars, validated before the event resolves — `routes/redemption_events.py:201-203`
- §3.4 (reversal ledger) — insert — ambiguity — the event's own `provisional_release_cents`/`final_release_cents`/`remeasurement_delta_cents`/`partner_cost_cents`/`allocated_at` are **not** reset; agreement `version` untouched — `routes/redemption_events.py:231-240`
- §3.7 step 1 — insert — ambiguity — the period itself is excluded from the predecessor search, and no sibling is disqualified for ending later — `calc.py:210-224`
- §3.7 step 7 — insert — ambiguity — no `APPROVED` estimate ⇒ rate 0 ⇒ `required_liability_cents` 0 (preview-only situation) — `calc.py:235-238`
- §3.7 soft-close — insert — ambiguity — non-`OPEN` is `ERR_INVALID_STATE_TRANSITION` not `ERR_PERIOD_NOT_OPEN`; actual rejection order is estimate → unallocated → not-ended, not the narrative order; closes/reopens are not programme-status gated — `routes/periods.py:97-105`
- §3.7 reopen — insert — ambiguity — source-state test precedes the `reopen_count` budget — `routes/periods.py:129-132`
- §3.7 hard-close — insert — ambiguity — the memo test is against the empty string exactly, so whitespace-only counts as present — `routes/periods.py:144`
- §3.7 preview — revise — mismatch — "ask an open period" → available whatever the period's `state`, and may differ from the persisted close figures — `routes/periods.py:86-90`
- §3.8 ¶1 — insert — ambiguity — sweep not gated on programme `status`; answers 200 with the swept period — `routes/periods.py:163-169,213`
- §3.8 (dormancy) — insert — ambiguity — "touched" = a member with at least one lot actually expired; skipped-only members are not evaluated — `routes/periods.py:203-208`
- §3.8 (version details) — insert — ambiguity — programme/period increment even on an empty sweep; an expire-then-escheat lot gets exactly **one** `version` increment — `routes/periods.py:202,211-212`
- §4 `/accounting-periods/{id}` row — revise — mismatch — "eleven" → "twelve persisted rollforward figures of §3.2" — `serialize.py:49-58`
- §4 `/liability-rollforward` row — insert — ambiguity — "Accepted whatever the period's `state`" — `routes/periods.py:86-90`

Scope confirmation: scanned exhaustively `calc.py`, `routes/periods.py`, `routes/point_lots.py`, `routes/redemption_events.py`. No pass-1 or pass-3 passage patched (the two §2.8/§2.9 edits have `routes/periods.py`'s reopen path as their subject and were unavoidable, since impl never raises `ERR_PERIOD_HARD_CLOSED` on reopen). §2.4's window sentence left untouched per pass 1's note (b). Two `calc.py` behaviours deliberately deferred to pass 3 because their governing prose is §3.6: the `ERR_SENSITIVITY_BAND_INVALID` vs `ERR_NO_OUTSTANDING_POINTS` ordering, and the per-variant lot set for `outstanding_points_at_estimate`.

### Pass 3 of 3 — estimate / partner / settlement / change-order modules (`routes/partner_agreements.py`, `routes/breakage_estimates.py`, `routes/settlement_statements.py`, `routes/change_orders.py`)

**Size:** before 511 lines / 117,757 chars → after **511 lines / 127,351 chars** (+9,594). Ends at the real final boundary `| ERR_PROGRAM_CONFIG_INCOMPLETE | 409 |`; still 19 `###` subsections (no new sections added).

**Counts:** 21 edits — **16 ambiguity-pins, 5 mismatch-revisions**.

Changes:
- §2.7 — insert — ambiguity — both `expected_*_version` fields are non-negative integers; a negative/non-integer value is `ERR_INVALID_REQUEST` at rung 5, not a 412; no upper bound — `routes/breakage_estimates.py:154`, `routes/settlement_statements.py:36`
- §2.8 rung 4 — revise — mismatch — added single-partner-agreement read to the ownership list; "Five of those six" → "Six of those seven" — `routes/partner_agreements.py:85`
- §2.8 rung 4 — revise — mismatch — "The sixth, redemption request" → "The seventh" (consequence of the above)
- §2.8 rung 26 — revise — mismatch — removed statement create from `ERR_AGREEMENT_PROGRAM_MISMATCH`; that error is never raised there, the disagreement surfaces at rung 24 — `routes/settlement_statements.py:46`
- §2.8 rung 36 — insert — ambiguity — pinned the band-vs-no-points ordering both ways, incl. the `COHORT_WEIGHTED` exception that outranks rung 31 — `calc.py:164` vs `routes/breakage_estimates.py:44-47`
- §3.5 ¶279 — insert — ambiguity — `relationship_type` is descriptive only; nothing branches on it — `routes/partner_agreements.py` (no consumer)
- §3.5 ¶281 — insert — ambiguity — conflict test is one-directional, same-programme/same-`partner_code` only, and is the sole consumer of the effective window — `routes/partner_agreements.py:44-54`
- §3.5 ¶283 — revise — mismatch — statement-create programme disagreement is always `ERR_PERIOD_PROGRAM_MISMATCH`, never `ERR_AGREEMENT_PROGRAM_MISMATCH`; noted `SOFT_CLOSED` is accepted — `routes/settlement_statements.py:44-47`
- §3.5 ¶285 — insert — ambiguity — a lot's `settlement_state` is irrelevant to measurement, so re-measuring a settled pair re-bills the same issuance — `calc.py:260-264`
- §3.5 ¶294 — insert — ambiguity — only `DRAFT` siblings are superseded; `SUPERSEDED` is terminal — `routes/settlement_statements.py:63-70`
- §3.5 ¶296 — revise — ambiguity — issue also requires the period not to be `HARD_CLOSED` — `routes/settlement_statements.py:104`
- §3.5 ¶298 — insert — ambiguity — `dispute_reason`/`resolution_note` required, non-blank, ≤500 chars; dispute validates after the ownership test, resolve validates before path resolution — `routes/settlement_statements.py:120-122,137-139`
- §3.5 ¶298 — insert — ambiguity — dispute and resolve are gated on neither the period's `state` nor the agreement's `status` — `routes/settlement_statements.py:116-146`
- §3.5 ¶300 — insert — ambiguity — pay and write-off refuse `HARD_CLOSED` and are not gated on agreement `status` — `routes/settlement_statements.py:156,181`
- §3.5 ¶300 — insert — ambiguity — `write_off_reason` required, non-blank, ≤500 chars, validated before path resolution — `routes/settlement_statements.py:175-177`
- §3.5 ¶300 — insert — ambiguity — the `ACTIVE → SUSPENDED` cascade is conditional; an already-suspended/terminated agreement keeps its status but still takes `version` +1 — `routes/settlement_statements.py:192-194`
- §3.6 ¶306 — insert — ambiguity — the four create preconditions are narrative order; evaluation is `ERR_PERIOD_NOT_OPEN` → `ERR_PROGRAM_NOT_ACTIVE` → period mismatch → cohort mismatch — `routes/breakage_estimates.py:34-41`
- §3.6 ¶308 — revise — ambiguity — the no-weighted-cohort case rejects with `ERR_NO_OUTSTANDING_POINTS` **before** the band check (pass 2's deferred item) — `calc.py:164`
- §3.6 ¶317 / ¶322 / ¶323 — revise — ambiguity — pinned the per-variant lot set for `outstanding_points_at_estimate` (`SINGLE_COHORT` = that cohort's lots; `COHORT_WEIGHTED` and `PROGRAM_HISTORICAL` = the programme's whole outstanding lot set, taken directly, not re-derived from candidate weights), plus the band-check-first ordering for both knowable-rate variants (pass 2's deferred item) — `calc.py:144-177`, `routes/breakage_estimates.py:44-47`
- §3.6 ¶325 — insert — ambiguity — each bound is compared only against the rate; a crossed low/high pair is `ERR_SENSITIVITY_BAND_INVALID`, not a shape error — `routes/breakage_estimates.py:29-30,44-45`
- §3.6 ¶329 — insert — ambiguity — period test outranks the source-state test on both submit paths; reject is not period-gated; `rejection_reason` required, non-blank, ≤500 chars, validated before path resolution — `routes/breakage_estimates.py:101-104,119-121`
- §3.6 ¶331 — insert — ambiguity — approve evaluation order (412 → period → state → SoD) and that approve is **not** gated on programme `status` — `routes/breakage_estimates.py:155-165`
- §3.9 ¶379 — insert — ambiguity — a past `effective_at` is `ERR_INVALID_REQUEST` at rung 5, reported ahead of a non-existent `program_id`; equality accepted — `routes/change_orders.py:53-55`
- §3.9 ¶381 — revise — **mismatch** — `projected_outstanding_gross_ssp_cents` reprices at a *single programme-wide* price (`new_ssp` for `SSP_CHANGE`, the programme's current `ssp_millicents_per_point` otherwise) and never consults a lot's own snapshot; the old claim that the two grosses are always equal for `EXPIRY_DAYS_CHANGE`/`TIER_MULTIPLIER_CHANGE` is now correctly conditioned on no stale per-lot price snapshots — `calc.py:307-316`
- §3.9 ¶385 — insert — ambiguity — apply also requires programme `ACTIVE`; equality with `effective_at` suffices; rung order `ERR_PROGRAM_NOT_ACTIVE` → `ERR_INVALID_STATE_TRANSITION` → `ERR_CHANGE_NOT_YET_EFFECTIVE` — `routes/change_orders.py:122-128`

Confirmations: slice scanned exhaustively; no pass-1/pass-2-owned passages patched (§2.8 rungs 4 and 26 were touched only to correct enumerations of pass-3 endpoints); passes 1 and 2's edits verified intact and the file grew monotonically 117,757 → 127,351 chars. **Verdict on pass 2's `ERR_PERIOD_HARD_CLOSED` wording: accurate, no correction needed** — a full grep confirms the code is raised at exactly four sites, all in `routes/settlement_statements.py` (`:45` create, `:105` issue, `:157` pay, `:182` write-off); nothing in `periods.py` raises it.

### Orchestrator note (Step 9 verification)

Independently verified on disk: `PRD_COMPLETED.md` is 511 lines / 127,351 chars against `PRD_FINALIZED.md`'s 510 / 101,652 — a +25.3% char delta, so the scan demonstrably ran and the file is NOT byte-identical to its source. `cmp` confirms it differs; the top-level structure §1–§5 is intact and the file still ends on the last row of the §5 error table. 68 total edits across the three passes (21 + 26 + 21), of which 13 were mismatch-revisions and 55 ambiguity-pins. Stray `__pycache__`/`.pytest_cache` directories swept from the task tree.

## Pipeline complete — 2026-09-04T18:42:00.000Z

All nine steps finished. Final state: 213 tests, 8/8 sweep rounds at 213/213, `workspace/PRD_COMPLETED.md` written.
