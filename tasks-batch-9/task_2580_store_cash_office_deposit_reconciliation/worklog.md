# Worklog — task_2580_store_cash_office_deposit_reconciliation

## Step 1: Create task directory — 2026-09-03T15:11:00.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2580_store_cash_office_deposit_reconciliation` and its `workspace/` subdirectory. Index 2580 was pre-assigned by the invoking pipeline; no scan of `./tasks/` was performed and no other task directory was created.

## Step 2: Generate scaffold — 2026-09-03T16:31:00.000Z

Scaffold generation for task 2580 is complete and lints clean.

Files (all under `/home/ubuntu/github/CodingPRD/tasks/task_2580_store_cash_office_deposit_reconciliation/`)

| File | Lines | Bytes | Top-level key(s) |
|---|---|---|---|
| `SCAFFOLD.yaml` | 2329 | 133 KB | scenario, domain_name, api_prefix, complexity_profile, response_envelope, entities, state_machines, concurrency_rules, calculations, validations, endpoints, errors, roles (no design keys) |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 1624 | 102 KB | `scaffold_difficulty_design` only |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 4311 | 248 KB | `scaffold_corner_design` only |

Counts
- §1.1–§1.7: 11 entities, 7 state machines, 2 concurrency (OCC) rules, 8 calculations, 15 ordered validations (priorities 10–68), 53 endpoints, 43 errors, 6 roles.
- §1.8: 9 rule_ids × 2 instances = 18.
- §1.9: 78 instances across all nine claim-extraction sections — entities 11, state_machines 15, calculations 11, validations 18, endpoints 5, errors 3, rbac 8, cross_cutting_complexity_layers 6, consistency_model 1 (13 of those are `excluded_because:` stubs pointing at the §1.8 instance that already covers the corner).
- Lint: `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5` (884 calls scanned).
- All 43 error ids are triggered by at least one §1.8/§1.9 instance (verified by scanning both design files against the catalog).

Design adjudications
- **`TillSession.safe_id` added** to §1.1: the assignment endpoint already accepted `safe_id` and drops/verified-drops depend on the session's safe, but the field was missing. Its FK then failed reverse-reachability, so `GET /cash-ops/till-sessions` gained a `safe_id?` filter (input is now `["sales_journal_id?", "cashier_id?", "safe_id?", "status?"]`).
- **Store-scoped FK resolution at priority 35**: a Cashier or Safe whose `store_id` differs from the journal's is treated as non-existent (`ERR_CASHIER_NOT_FOUND` / `ERR_SAFE_NOT_FOUND`) so no caller can enumerate another store's rows.
- **Dual control binds the bag as well as the door** (priority 52, before the priority-56 time-delay check): the sealer must differ from `prepared_by_user_id`, and the response never reveals whether the delay had elapsed.
- **Ordering adjudications** baked into recipes: seal relocks the safe (so the pickup-capacity corner uses two separate openings); `ERR_SAFE_FROZEN` (45) outranks `ERR_CASHIER_BARRED` (50), so the barred-cashier corner closes the case SUBSTANTIATED first; capacity (62) vs window conflict (58) disambiguated with buffered-disjoint windows and `max_daily_pickups: 1`; priority 20 precedes 40, so `store_manager_cannot_close_a_variance_case` returns `ERR_UNAUTHORIZED` on an OPEN case rather than a state error.
- **Forced close semantics**: `forced_close: true` leaves `pos_*` null and makes reconcile an `ERR_INVALID_REQUEST` (priority 25), not a state error.
- Boundary literals re-derived and pinned: single-event threshold is `>=` (17500 vs 20000 expected fires at exactly −2500; 17501 does not), carrier fee `1200 + 35*ceil(declared/100000)`, card-settlement tiers with the AMEX +0.0035 adder rounded half-up on the percentage only, BASELINE change-order plan totalling 613000 against a 560000 forecast, and the Safe version walk 1→2→3→4→5 (create, arm, open, prepare, seal) with reads never incrementing.
- Late corrections found while cross-checking against §1.1 field names: `over_short_cents`→`variance_cents`, `counted_total_cents`→`counted_cash_cents`, `drop_total_cents`/`drop_count`→`dropped_declared_cents`/`dropped_verified_cents`, `rolling_variance_cents`→`rolling_absolute_variance_cents`, `investigation_posture`→`posture`, `closed_by_user_id`→`escalated_by_user_id`; plus payload fixes for `/drops` (`txn_type`, `declared_amount_cents`), `/schedule-pickup` (`carrier_reference`), `/pickup` (`picked_up_at`, `carrier_signature`) and `/reconcile-bank` (`bank_credit_record_ids`). A blind-count assert was also corrected: `expected_cash_cents`/`variance_cents` stay null and masked until reconcile.
- Two intentional lint-invisible payload deviations remain (both negative/ignored-input corners): `cashier_creation_missing_display_name_returns_invalid_request` omits a required field, and `change_order_client_supplied_total_planned_cents_input_ignored` sends an undeclared computed field.

No sibling task directory was read, listed, or grepped at any point.

## Step 3: Copy shared files — 2026-09-03T16:32:00.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` to `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-03T16:45:00.000Z

PRD generated at `workspace/PRD.md` — **394 lines**, ending at the last row of the **§5 Error Code Catalogue** table (`| \`ERR_CLOCK_MONOTONIC\` | 422 |`), a clean section boundary.

Structure: §1 Introduction (3 paragraphs), §2 with 12 domain-derived subsections (roles/header identity, the fixed response envelope, pagination, identity+logical clock, store policy parameters, safe ledger, dual control, time-delay device, investigation freeze, money/denominations/rounding, stale-version rejection, validation precedence), §3 with 9 workflow subsections, §4 endpoint table (53 endpoints, 4 columns), §5 error table (43 codes, 2 columns).

Hard Contract Reports

```
Field coverage check:
- entities[].fields: 124 required, 124 present, 0 missing
- endpoints[].request_body: 81 required, 81 present, 0 missing
- endpoints[].query_params: 19 required, 19 present, 0 missing
- nested array item fields (counted_lines / planned_lines / attributions): 9 required, 9 present, 0 missing
- errors[].id: 43 required, 43 present, 0 missing
- roles[].name: 6 required, 6 present, 0 missing
- state values: 27/27 atomic states present (the 28th entry is the composite label "ELIGIBLE x NONE"; both components appear)
- enum-type field values: 64 required, 64 present, 0 missing
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: 15 checked, 15 expressed in prose as an explicit 15-step precedence order in §2.12 (including the three deliberate ordering notes: freeze-before-dual-control/time-delay, dual-control-before-time-delay, fiscal-after-state), 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write_endpoint + expected_safe_version / expected_variance_case_version + error_id + 412 all named in §2.11), 0 missing
- state_machines[].transitions: 45 checked, 45 fully expressed, 0 missing
- calculations[]: 8 checked, 8 fully expressed with all constants, pinned evaluation orders and the two worked divergences the scaffold nominates (carrier fee on 200500; per-line vs sum-then-round on 1008000), 0 missing
- validations[] conditions: 15 checked, 15 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 53 endpoints checked, all side-effect sets expressed; the 5-operation ERR_SAFE_FROZEN scope and the 2-operation dual-control scope enumerated exhaustively, 0 missing
- entities[].fields[] structured content: 124 checked, defaults / initial values / null-until conditions / uniqueness constraints / ranges reconstructible from prose, 0 missing
- sibling-branch symmetry: 7 groups checked (deposit RECONCILED vs DISCREPANT; case EXPLAINED vs ESCALATED; CLOSED_SUBSTANTIATED vs CLOSED_UNSUBSTANTIATED; provisional credit smart vs carrier; till over/short declared vs verified drops; change order APPROVED vs REJECTED; void from PREPARING vs SEALED), 7 with equal prose density, 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 845
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
- unticked "/cash-ops" occurrences in §3: 0
Status: PASS
```

Additional verifications: §2.2 is **byte-identical** to `section-2.2-response-structure.md`; no fuzzy/approximating words anywhere in the document; §4 has exactly 4 columns and §5 exactly 2.

Two scaffold-internal conflicts resolved deliberately by the doc generator, worth flagging:
- **`verify_till_session_ids` semantics.** The scaffold's endpoint list takes a bare list of session ids, while the Deposit state machine speaks of a per-entry `verified_total_cents`. Specified the deterministic reading: mid-shift drop rows verify at their declared amounts, the closing drop row absorbs the residual, and a session's share of the re-count is the deposit's `declared_total_cents` apportioned by `dropped_declared_cents` (reducing to the whole deposit total in the single-session case).
- **Escalation entry state.** §1.2 declares only `RESEARCHING → ESCALATED`; the endpoint's side-effects say "OPEN or RESEARCHING". Used the broader endpoint wording. Other resolutions favoured the entity field definitions over endpoint prose (`register_cash_tieout_cents`, `settlement_variance_total_cents` as a sum of absolute values) and `days_covered` 1–14 over the entity's 1–31, matching the error catalogue.

ORCHESTRATOR VERIFICATION (truncation guard): independently ran `wc -l -c`, `tail -20`, and `grep -n '^#'` on PRD.md. 394 lines / 86854 bytes; final line is a complete error-table row; all 5 top-level sections plus 12 §2 subsections, 9 §3 subsections, §4 and §5 present. NOT truncated — no regeneration needed.

## Step 6: Generate implementation — 2026-09-03T17:12:00.000Z

The implementation is complete and verified.

Files written (all under `workspace/implementation/`)

| File | Lines |
| --- | --- |
| `start.sh` (executable, guarded pip install, `exec python3 app.py`) | 10 |
| `requirements.txt` (`Flask==3.0.3`) | 1 |
| `app.py` | 83 |
| `auth.py` | 65 |
| `calc.py` | 150 |
| `clock.py` | 60 |
| `db.py` | 55 |
| `domain.py` | 367 |
| `errors.py` | 65 |
| `response.py` | 87 |
| `serializers.py` | 267 |
| `validation.py` | 187 |
| `routes/common.py` / `clock_routes.py` / `stores.py` / `cashiers.py` / `safes.py` / `journals.py` | 30 / 21 / 76 / 90 / 151 / 143 |
| `routes/sessions.py` / `deposits.py` / `bank.py` / `cases.py` / `change_orders.py` | 331 / 450 / 71 / 197 / 137 |

Total 3083 lines; every file passes `ast.parse`. **53 routes registered**, matching the 53 rows in the PRD §4 endpoint table / scaffold endpoint list exactly. Storage is 11 module-level dicts; a fresh boot returns `total_count: 0` for every collection (verified) — nothing is seeded.

Smoke test result
Two scripted scenarios against `PORT=41000 bash start.sh` (single pid killed afterwards; no broad pkill):
- Happy path (33 assertions, 0 failures): store defaults, safe commissioning, journal + tenders, till assignment with masked `expected_cash_cents`, time-delay refusal then open after clock advance, drop, close projection (exactly the 6 declared keys), blind-count projection (5 keys), dual-control reconcile (expected 30000 / variance 0), deposit prepare (declared 242000 → fee **1305**, expected credit **240695**), seal relocks safe, schedule, pickup, bank record, reconcile-bank → RECONCILED, AMEX settlement (fee 1395, MATCHED), journal reaching **BALANCED**, change order forecast **1008000** → planned total **1106000** (both PRD examples), pagination meta, 403/401/404 paths.
- Investigation path: smart insertion provisional **196000** (vs 242000 carrier on identical cash), `SMART-SAFE-S` seal, `ERR_SMART_SAFE_REQUIRED`, short reconcile −110000 → coaching + 2 cases, over-attribution 422, suspected-theft case staying RESEARCHING at zero unexplained, escalate → both safes FROZEN + cashier BARRED, restore blocked while escalated, close UNSUBSTANTIATED → safes OPEN + reinstatement to RESTRICTED, ownership 403, clock monotonic 422. The only mismatch was the agent's own test expectation: a barred cashier at a frozen store correctly returns `ERR_SAFE_FROZEN` (precedence 7 before 8).

PRD/scaffold adjudications (PRD wins)
- `created_at`/`updated_at` use the **logical** clock (the rolling window compares `TillSession.updated_at` to it); `api_request_timestamp` uses wall time. List order and "earliest safe" use `(created_at, _seq)` for a stable tie-break.
- Safe `open_state` (`ERR_SAFE_NOT_UNLOCKED`) is checked **before** posture (`ERR_SAFE_FROZEN`) per §2.12's explicit "Sixth… Seventh" ordering, against §3.4's prose enumeration.
- Register close does **not** check the freeze (§2.9 lists only five frozen-blocked operations; close is not one) even though the scaffold's transition lists it.
- Reconcile's null-`pos_cash_sales_cents` 400 is gated on `forced_close`, so reconciling an ACTIVE session still yields `ERR_TILL_SESSION_INVALID_STATE`.
- `dropped_verified_cents` is null when a session has no drop rows at all → `DECLARED_DROPS`.
- `days_covered` 1..14 (PRD) not 1..31 (scaffold entity); pickup capacity keyed on `business_date` (PRD) not `pickup_window_start`'s date (scaffold priority 62b).
- Escalation available from OPEN or RESEARCHING; gate = magnitude ≥ threshold OR the cashier has ≥2 other cases created in the preceding 90 days.
- `carrier_reference` is required at schedule-pickup (scaffold input) and stored there, since no later endpoint accepts it.
- Derived fields (safe balance/provisional/suspect, journal tie-outs and counts, case bucket totals, cashier `open_case_count`) are computed lazily; only clock-window snapshots (cashier rolling figures) and `credited_total_cents`/`credit_variance_cents` are stored. Provisional/suspect pools exclude RECONCILED **and** VOIDED deposits, reconciling the lazy formula with the void side effects.
- Uniqueness with no catalogued error (store_code, employee_code per store, safe_code per store) → `ERR_INVALID_REQUEST`; `restore-posture` with an ESCALATED case → `ERR_VARIANCE_CASE_INVALID_STATE`; `acknowledge-coaching` when not COACHING_DUE → `ERR_INVALID_REQUEST`.
- Force-closed sessions in the escalation cascade get a `version` bump under §2.4's general mutation rule (PRD's version enumeration there lists only case/cashier/safes); till sessions whose drop rows get verified at deposit-prepare do **not** (no record field changes).
- Rolling-threshold breach sets RESTRICTED only from ELIGIBLE, so an already-BARRED cashier is not silently un-barred; the ROLLING_PATTERN case still opens.

ORCHESTRATOR NOTE: Steps 5 and 6 were launched as background agents. Due to an orchestrator slip they went out in two consecutive messages rather than one, so Step 6 started a few seconds after Step 5 instead of simultaneously. Step 6's prompt carried an explicit absolute prohibition on reading `test_helpers/`, `test_suite/`, the two SCAFFOLD_*_DESIGN.yaml files, and sibling tasks, and its summary shows it worked purely from PRD.md + SCAFFOLD.yaml + INSTRUCTION.md (its adjudication list is entirely PRD-vs-scaffold, with no test references, and it hit a self-authored smoke-test expectation mismatch rather than a test-suite one). Isolation is therefore considered intact.

## Step 5: Generate unit tests — 2026-09-03T17:20:00.000Z

All 11 generator agents are done and the suite passes both mandatory audit passes.

Location proof

Task root contains `test_helpers/` and `test_suite/` as siblings of `workspace/`. `workspace/` holds only `INSTRUCTION.md`, `PRD.md` and `implementation/` — neither test directory is inside it.

Files written

`test_helpers/` — 2460 lines total: `__init__.py` 50, `api_client.py` 270 (55 endpoint methods over `PREFIX="/cash-ops"`), `api_errors.py` 105 (43 error ids registered via `set_error_http_status_map`), `assertions.py` 381, `constants.py` 93, `factories.py` 245, `fixtures.py` 782 (5 fixture tiers), `test_users.py` 88, `types.py` 446.

`test_suite/` — 9184 lines total: `conftest.py` 92 plus 19 test files. Queue A: `test_01` 431, `test_02` 250, `test_03` 401, `test_04` 506, `test_05` 276, `test_06` 413, `test_07` 397, `test_08` 293, `test_09` 381. Queue B: `test_10` 741, `test_11` 977, `test_12` 857, `test_13` 600, `test_14` 412, `test_15` 449, `test_16` 278, `test_17` 758, `test_18` 470, `test_19` 202.

Tests emitted

**106 tests collected** (`pytest --collect-only` clean, all modules import, pyflakes clean apart from the barrel's intentional re-exports).

- Queue A (depth): **42 tests** covering **18/18** difficulty instances, every one with ≥2 tests (six have 3).
- Queue B (breadth): **64 tests** covering **64/65** non-stub corner instances at ≥1 test each.

Audit results: 0 untagged tests, 0 dual-tagged tests, 0 unresolved `Design:` tags, 0 tags pointing at stubs, `Design:` is the last docstring line everywhere, no `skip`/`skipif`/`xfail` anywhere, and all **248** quoted PRD sentences verify as literal substrings of `PRD.md`. All **13** `excluded_because:` stubs emit no tests and all 13 `difficulty_instance:` pointers resolve to real names in `SCAFFOLD_DIFFICULTY_DESIGN.yaml`.

Instance skipped (1)

`Corner/entities/change_order_client_supplied_total_planned_cents_input_ignored` — **computed-field**. §3.9 derives `total_planned_cents`, but no PRD sentence says a client-supplied server-derived field is *ignored* rather than rejected; §2.12's body-shape step is silent on extra fields and §2.11's "no other endpoint accepts a version field" is scoped to version fields. Two PRD-only implementers could legitimately answer 201-ignoring or 400, so the YAML's asserted 201 is not uniquely derivable.

Adjudications (PRD won every time)

1. **Dual control on till reconcile** — six YAML recipes blind-count *and* reconcile as `U-CLERK-3` against stores with `dual_control_required: true`, which PRD §2.7/§3.5 make `ERR_DUAL_CONTROL_VIOLATION`, so the setups could never reach the arithmetic under test. Counter kept at `U-CLERK-3`, reconciler switched to a different clerk; no asserted figure depends on reconciler identity.
2. **Literal timestamp strings** — PRD §2.4 renders instants with three fractional digits, so YAML asserts like `created_at == "2026-08-03T08:00:00Z"` can never hold. Compared through `parse_instant(...)` on both sides instead (instant preserved, rendering not bet on).
3. **`register_cash_tieout_cents` literals dropped** in two recipes that never post tenders (`journal_cash_sales_cents` null → no PRD-defined subtrahend); `status == OUT_OF_BALANCE` replaced with the §3.1-necessary `OPEN` in one of them. Category: computed-field; only those assertions dropped, instances still covered.
4. **`consistency_model` case counts corrected** — its own `-60000` variance breaches the default 10000 rolling threshold, so §3.5 opens a second `ROLLING_PATTERN` case: asserted `open_case_count == 2` and `net_unexplained_cents == 120000`, not the YAML's 1/60000.
5. **`each_role_performs_its_own_exclusive_operation`** — recipe's `variance_cents == -60000` doesn't follow from its own inputs (§3.5 gives 0); `pos_cash_sales_cents` raised to 160000 so the PRD formula yields exactly the YAML's asserted outcome. Its non-existent `DEPOSIT_VOID` txn_type replaced with the §2.6/§3.6 kind `DEPOSIT_RETURN`; a missing safe-open cycle added, and the recipe's second arm+open dropped (would answer `ERR_SAFE_OPEN_REQUEST_ACTIVE`).
6. **`days_covered` is 1..14** per PRD §2.12/§3.9 (scaffold's "1..31" loses).
7. **The two `priority_pair_validation_conflict` orderings are NOT validation-priority skips** — PRD §2.12 states both orderings verbatim ("returns `ERR_SAFE_NOT_UNLOCKED`, not `ERR_INSUFFICIENT_SAFE_BALANCE`"; dual control "deliberately ahead of the time-delay check"), so both pass the PRD-first filter.
8. **Ownership error id** — §2.1 uniquely names `ERR_UNAUTHORIZED` for a Cashier acting on another cashier's session, so no `validate_error_is_one_of` hedge was needed.
9. **Unobservable claims dropped** rather than guessed: "no Store with store_code S-1907 exists afterwards" (no list-stores endpoint), and the design-index statement about absent verbs on `/safe-transactions` (re-expressed observably as no `version`/`updated_at` on the row).

ORCHESTRATOR VERIFICATION: `ls` confirms `test_helpers/` and `test_suite/` are at the task root (not under `workspace/`); `find workspace -name 'test_*' -type d` returns nothing. 19 test modules + conftest.py present.

## Step 7: Run tests and iterate — 2026-09-03T17:32:00.000Z

Fully green. Final sweep: **8/8 rounds, 106/106 tests passed each round, 0 failures, 0 errors.**

**Iterations run:** 2 sweeps (8 parallel rounds each, `setsid nohup`, per-test-server isolation).

Sweep 1: 99/106 in every round — 7 failures, identical in all 8 rounds (fully deterministic, no flakiness signal). Sweep 2 after fixes: 106/106 in all 8 rounds.

**Tests deleted:** none. All 7 failures survived STEP 1 (PRD verbatim-covers + uniquely derivable) and were resolved at STEP 2 as test bugs.

**Fixes applied to `test_suite/` (7 sites, 2 root causes):**

1. *Literal-timestamp rendering mismatch (6 sites).* Tests compared instant fields to bare-second literals (`"2026-08-06T17:00:00Z"`) while the server renders `"...T17:00:00.000Z"`. PRD §2.4 pins instants as "the ISO 8601 UTC instant with **three fractional digits**", so the implementation's rendering is the PRD-faithful one and the assertion was mis-translating. The suite already had the correct pattern in 6 other places (`parse_instant(...)` on both sides — the generator's own documented adjudication #2); these 6 had been missed. Fixed by comparing through `test_helpers.fixtures.parse_instant`, which preserves the exact instant assertion while not betting on rendering. `parse_instant` import added to each file.
   - `test_01_dual_variant_calculations.py:200` (`coaching_due_at`)
   - `test_12_derived_money_calculations.py:95` (`occurred_at`), `:348`, `:767` (`coaching_due_at`)
   - `test_15_endpoint_behaviours.py:99` (`coaching_due_at`)
   - `test_16_error_reachability.py:170` (`open_requested_at`)

2. *`test_08_temporal_overlap_windows.py::test_pickup_window_one_minute_clear_of_the_buffer_is_accepted` — bad request arithmetic.* The "accepted" leg requested `11:01Z–11:31Z` against a store with `pickup_buffer_minutes: 30` and an already-scheduled D1 of `10:00Z–10:30Z`. Per PRD §3.6 both windows expand on both sides: D1 → `09:30Z–11:00Z`, the request → `10:31Z–12:01Z`. Those closed intervals genuinely intersect on `[10:31, 11:00]`, so the implementation's `ERR_PICKUP_WINDOW_CONFLICT` was correct — the window was never "one minute clear". Corrected the request to `11:31Z–12:01Z` (expands to `11:01Z–12:31Z`, clearing D1's expanded end by exactly one minute), plus the two window-echo assertions, preserving the test's stated intent.

**Fixes applied to `implementation/`:** none. Both the three-fractional-digit instant rendering (`response.py`/`serializers.py`) and the closed-interval both-side buffer expansion (`routes/deposits.py:schedule_pickup`, lines 305–322) were already PRD-faithful; no implementation check was weakened and nothing was added or seeded.

**Fixes applied to `test_helpers/`:** none needed — `parse_instant` already tolerated both renderings; the bug was in the 6 test-suite call sites that bypassed it.

ORCHESTRATOR VERIFICATION (sweep-artifact check): independently listed and parsed all 8 `workspace/implementation/results.{1..8}.json` (each ~32 KB, all written 17:27). Every round reports `passed 106 / total 106 / failed 0 / errors 0`. The green claim is confirmed against real artifacts, not just the subagent's report.

ORCHESTRATOR DECISION on Step 8: Step 7 applied **0 implementation/ fixes** and **0 deletions**, but it did apply **7 test_suite/ fixes** across 2 root causes, so this is NOT the skip condition (which requires zero iterations beyond baseline — zero deletions AND zero test_suite fixes AND zero test_helpers fixes AND zero impl fixes). Two full sweeps ran. Step 8 therefore runs, with the two root causes as its focus list: PRD §2.4's instant rendering and PRD §3.6's pickup-window buffer expansion are both places where the test generator read the PRD differently than the implementer did, i.e. candidate PRD-ambiguity sites even though the implementation needed no change.

## Step 8: Finalize PRD — 2026-09-03T17:38:00.000Z

Done. `PRD_FINALIZED.md` is written with a single one-paragraph insertion.

**Line counts:** PRD.md 394 → PRD_FINALIZED.md 396 (+2 lines, +0.51%; one paragraph plus blank line).

**Changes**
- §2.4 Record Identity, Versioning and the Logical Clock — insert — pins that *every* instant-valued response field (not just `created_at`) renders as ISO 8601 UTC with exactly three fractional digits and a trailing `Z`, that client-supplied instants are normalized into that form (UTC-converted, sub-millisecond precision truncated), that unset instants are null, and that calendar-date fields are not instants — `clock.py:36-44` (`fmt`), `clock.py:46-58` (`parse`), `serializers.py:8-14, 44, 61, 63, 99-100, 126, 154-156, 176-177, 225`, `response.py:25`, `routes/clock_routes.py:21`.

**Per-edit pre-edit search log**
- (a) Subject: rendering of instant-valued fields in API responses (the root cause behind the 6 literal-timestamp test fixes).
- (b) Impl paths enumerated: `clock.fmt` (the sole renderer; `%03d` of `microsecond // 1000` → truncation, `None` → `None`, `str` passthrough branch is dead because all stored instants are `datetime`); `clock.parse` (accepts `Z`/`z`, offsets, naive strings; always `astimezone(utc)`); `validation.req_datetime`/`opt_datetime` (all client instants parsed to `datetime` before storage, so nothing is echoed verbatim); every `clock.fmt` callsite grepped — `serializers._common` (`created_at`/`updated_at`), `cashier.coaching_due_at`, `safe.open_requested_at`/`unlocked_at`, `till_session.shift_start_at`/`shift_end_at`, `close_projection.shift_end_at`, `safe_transaction.occurred_at`/`created_at`, `deposit.pickup_window_start`/`_end`, `variance_case` attribution `recorded_at`, `response._meta.api_request_timestamp`, `routes/clock_routes.set_current_utc` echo of `current_utc`; ad-hoc `*_at` writes in `routes/cases.py:58`, `routes/safes.py:40-42`, `routes/sessions.py:109-110`, `routes/cashiers.py:47` (all store `datetime` or `None`); `validation.req_date` + its 5 callsites (`business_date` ×2, `value_date`, `target_week_start`) confirming date-only fields are validated `YYYY-MM-DD` and re-emitted unchanged. Empirically verified `fmt(parse(...))` for 7 input spellings.
- (c) Wording adjustments: initially wrote "more than three of them"; after testing that `.1239Z`/`.123456789Z` truncate to `.123Z`, widened to "more or fewer than three of them" and added the explicit sub-millisecond-truncation clause so no path is mis-described. Scoped the universal claim to *instant-valued* fields and named the three calendar-date fields as excluded, so the sentence cannot be read as forcing `business_date`/`value_date`/`target_week_start` into instant form. Deliberately made no claim about which clock (logical vs wall) feeds each field, since `api_request_timestamp` uses `clock.wall_now()` while all record stamps use the logical clock.

**Checked and deliberately left verbatim**
- §3.6 pickup-window buffer rule (PRD line 228) is already tight and exactly matches `routes/deposits.py:305-322`: the requested window expands by the store's `pickup_buffer_minutes` on both sides, the sibling window is "identically expanded", intervals are explicitly "treated as closed, so two windows that merely touch after expansion **do** conflict", the sibling set is same-store `SCHEDULED`/`IN_TRANSIT`, and the deposit itself is excluded. The Step 7 failure there was purely bad fixture arithmetic (the "one minute clear" window genuinely overlapped), so no PRD change is warranted.
- No other edits: the Step 7 diff contained zero implementation fixes, zero test deletions, and zero `test_helpers/` changes.

ORCHESTRATOR VERIFICATION: `wc -l` gives PRD.md 394 / PRD_FINALIZED.md 396; `diff` shows exactly one inserted paragraph in §2.4 and no other hunks. Not a byte-identical copy, so the finalizer genuinely ran.

## Step 9: Complete PRD — 2026-09-03T17:55:00.000Z

`workspace/PRD_COMPLETED.md` is written. Verification: `diff | wc -l` = **202** (51 changed line-blocks, all in-place paragraph revisions), line count **396 → 396** (no new sections or paragraphs), chars **88,006 → 99,700** (+11,694). Markdown tables and all 28 headings unchanged.

Counts: **51 changes = 34 ambiguity-pins + 17 mismatch-revisions.**

**Pass A — infrastructure/core (7)**
- §2.1 — revise — ambiguity — blank/whitespace headers treated as absent; role trimmed then matched case-sensitively — auth.py:24-30
- §2.2 — revise — ambiguity — `api_request_id` = `req_` + 20 uppercase alnum; `api_request_timestamp` read from wall clock, not the logical clock — response.py:19,25
- §2.3 — revise — ambiguity — non-integer `limit`/`offset` also `ERR_INVALID_REQUEST` — response.py:53-64
- §2.3 — revise — ambiguity — equal `created_at` ordered by server write sequence — db.py:53
- §2.3 — insert — ambiguity — filters compared as text; unknown value narrows to zero rather than 400 — routes/common.py:8-24
- §2.4 — revise — ambiguity — `created_at`/`updated_at` read the logical clock — db.py:32-50
- §2.4 — revise — ambiguity — clock endpoint `data` carries only `current_utc` — routes/clock_routes.py:21
- §2.12 — revise — ambiguity — body must be a JSON object, absent body = `{}`, required strings non-empty, `null` optionals ignored, bool/fractional in int fields fail — validation.py:14-93

**Pass B — money/serialization/simple resources (13)**
- §2.5 — revise — ambiguity — duplicate `store_code` → `ERR_INVALID_REQUEST` — routes/stores.py:65-67
- §2.5 (×3) — revise — ambiguity — rolling/theft thresholds and provisional cap must be ≥ 0 — routes/stores.py:48-59
- §2.6 — revise — ambiguity — provisional-credit and suspect-note aggregates exclude `VOIDED` as well as `RECONCILED`, derived on read — domain.py:101-124
- §2.8 — insert — mismatch — arming/opening endpoints never inspect `safe_type`; a smart safe can be armed — routes/safes.py:56-100
- §2.9 — revise — mismatch — arming checks freeze; the open endpoint does not consult `posture` at all — routes/safes.py:64,73-100
- §2.10 — revise — mismatch — non-negativity binds supplied fields only; derived figures go negative — calc.py:70-81
- §3.1 — revise — ambiguity — null posted cash counts as 0 in the tie-out; all seven figures derived on read — domain.py:241-246
- §3.2 — revise — ambiguity — duplicate `employee_code` → `ERR_INVALID_REQUEST` — routes/cashiers.py:36-38
- §3.3 — revise — ambiguity — duplicate `safe_code` → `ERR_INVALID_REQUEST`; `opening_balance_cents` required ≥ 0 — routes/safes.py:27-31
- §3.3 — revise — ambiguity — restore-posture: `ERR_VARIANCE_CASE_INVALID_STATE` while escalated, no version bump on already-`OPEN` safes, answers the path safe — routes/safes.py:103-115
- §3.5 — revise — ambiguity — `dropped_verified_cents` also null when the session has no drop rows — domain.py:164-175
- §3.6 — insert — ambiguity — zero-value bag priced at base fee; `expected_credit_cents` may go negative — calc.py:65-71
- §3.7 — revise — ambiguity — `txn_count` and every advice figure must be ≥ 0 — routes/journals.py:92-96
- §2.12 — revise — ambiguity — a nonexistent record falls through the Cashier ownership check to the 404 — routes/cashiers.py:19-24

**Pass C — heavy workflows (31)**
- §2.6 — revise — mismatch — `till_session_id` also set on a `SMART_DEPOSIT` row — routes/deposits.py:220
- §2.6 — revise — mismatch — `system` actor never actually appears; every row has an identified caller — routes/cases.py:150
- §2.11 (×2) — revise — mismatch — `expected_safe_version` / `expected_variance_case_version` enforced only when supplied; exact-equality comparison — routes/deposits.py:117,142; routes/cases.py:34,48
- §2.11 — revise — mismatch — stale test is inequality, not "advanced past" — routes/deposits.py:142
- §2.12 — revise — mismatch — body-FK resolution order is per-endpoint (journal→cashier→safe; safe→journal→sessions) — routes/sessions.py:48-54, routes/deposits.py:125-129
- §2.12 / §3.4 / §3.5 (3 edits) — revise — mismatch — the null-cash 400 keys on `forced_close`; an uncounted session gets the state error — routes/sessions.py:247-253
- §3.2 — revise — ambiguity — wrong journal status → `ERR_TILL_SESSION_INVALID_STATE` — routes/sessions.py:56-60
- §3.2 — revise — ambiguity — shift-overlap tested before register occupancy; only `RECONCILED` is terminal — routes/sessions.py:79-94
- §3.2 — revise — ambiguity — assignment leaves the journal's `version` untouched — routes/sessions.py:135
- §3.4 — revise — mismatch — unlock check precedes freeze check; drops against a smart safe are not refused — routes/sessions.py:151-154
- §3.4 — revise — ambiguity — drop answers 201; authored memo text; blank memo replaced — routes/sessions.py:155-169
- §3.4 — revise — ambiguity — `pos_paid_out_cents` defaults to 0 on an ordinary close — routes/sessions.py:188-190
- §3.4 — revise — ambiguity — `forced_close` by a Cashier → `ERR_UNAUTHORIZED`; supplied figures shape-checked then discarded — routes/sessions.py:178-184
- §3.4 — revise — ambiguity — `counted_lines` is required on the blind count — routes/sessions.py:207
- §3.5 — insert — mismatch — rolling breach restricts only an `ELIGIBLE` cashier; a fresh `ROLLING_PATTERN` case each time — routes/sessions.py:294-303
- §3.6 — revise — ambiguity — balance sufficiency read pre-verification; `verify_till_session_ids` non-empty if supplied and not store-scoped — routes/deposits.py:118-141
- §3.6 — insert — ambiguity — multiple/absent closing drops; negative remainder — routes/deposits.py:93-106
- §3.6 — revise — ambiguity — system PROVISIONAL row's `value_date`/`bank_reference`/`match_state`; may be ≤ 0 — routes/deposits.py:56-70
- §3.6 — revise — mismatch — the void-time provisional subtraction is subsumed by the derived aggregates — routes/deposits.py:265-288
- §3.6 — revise — ambiguity — `picked_up_at`/`carrier_signature` required but not persisted — routes/deposits.py:341-342
- §3.7 — revise — ambiguity — hand-posted `PROVISIONAL` accepted; `ADJUSTMENT` may be zero; `deposit_id` must resolve — routes/bank.py:25-35
- §3.7 — revise — ambiguity — missing FINAL/ADJUSTMENT would be `ERR_INVALID_REQUEST` (unreachable) — routes/deposits.py:404-405
- §3.7 — insert — ambiguity — repeat non-zero reconciliation stays `DISCREPANT`, no second case — routes/deposits.py:408-423
- §3.8 — revise — ambiguity — attribution `note` required non-empty — routes/cases.py:33
- §3.8 — insert — ambiguity — attribution answers 200 with the whole case — routes/cases.py:67
- §3.8 — revise — ambiguity — pattern route counts sibling cases in any status, inclusive boundary; no-cashier case needs the magnitude route — routes/cases.py:84-93
- §3.8 — revise — ambiguity — only newly frozen safes bump `version` — domain.py:303-309
- §3.8 — revise — ambiguity — earliest-safe tie-break; no safe → no adjustment row, closure still succeeds — routes/cases.py:144-152
- §3.9 — revise — ambiguity — `growth_pct` exact-decimal, echoed as supplied (0 when omitted) — routes/change_orders.py:30-48
- §3.9 — revise — ambiguity — rejection also records `approved_by_user_id` — routes/change_orders.py:86
- §3.9 — revise — ambiguity — earliest-safe tie-break; no safe → `ERR_SAFE_NOT_FOUND` — routes/change_orders.py:99-101
- §4 — revise — ambiguity — 201 for drops and smart deposits; 200 for attributions — routes/sessions.py:169, routes/deposits.py:225, routes/cases.py:67

ORCHESTRATOR VERIFICATION (byte-identity guard): `md5sum` confirms PRD_FINALIZED.md (509372f5…) and PRD_COMPLETED.md (8a43d3b0…) differ; `diff | wc -l` = 202; 396 lines / 99,700 bytes vs 396 / 88,006. The scan genuinely ran — this is not the known byte-identical failure mode. File ends at the final `ERR_CLOCK_MONOTONIC` error-table row (clean boundary, not truncated).

ORCHESTRATOR VERIFICATION (test validity preserved): `find implementation -name '*.py' -newer implementation/results.1.json` returns nothing — Step 9 edited only PRD_COMPLETED.md and touched no implementation source, so the verified 8/8 × 106/106 sweep remains valid for the delivered implementation.

## PIPELINE COMPLETE — 2026-09-03T17:56:00.000Z

All nine steps ran. Final artifacts in place: SCAFFOLD.yaml, SCAFFOLD_DIFFICULTY_DESIGN.yaml, SCAFFOLD_CORNER_DESIGN.yaml, worklog.md, test_helpers/ (9 modules), test_suite/ (conftest + 19 modules, 106 tests), workspace/{INSTRUCTION.md, PRD.md, PRD_FINALIZED.md, PRD_COMPLETED.md, implementation/ (22 modules + start.sh + requirements.txt), results.{1..8}.json}.
