# Worklog — task_2517_commercial_mortgage_special_servicing

## Step 1: Create task directory — 2026-09-03T04:14:28.147Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2517_commercial_mortgage_special_servicing/` and `.../workspace/`. Index 2517 was pre-assigned by the invoking pipeline (no ./tasks/ scan performed, per instruction, to avoid collision with the up-to-32 concurrent pipelines on this host).

## Step 2: Generate scaffold — 2026-09-03T06:02:12.147Z

Scaffold complete and lint-clean.

## Files (all in `/home/ubuntu/github/CodingPRD/tasks/task_2517_commercial_mortgage_special_servicing/`)

| File | Lines | Bytes |
|---|---|---|
| `SCAFFOLD.yaml` | 2,448 | 190,856 |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 2,786 | 200,629 |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 4,334 | 314,715 |

Top-level keys verified: `SCAFFOLD.yaml` contains neither `scaffold_difficulty_design` nor `scaffold_corner_design`; the other two each have exactly one top-level key.

## SCAFFOLD.yaml (§1.0–§1.7)

13 entities, 13 state machines, 2 concurrency rules, 13 calculations, 33 validations (priority-ordered), **53 endpoints**, 45 error codes, 7 roles. Difficulty target BEYOND EXPERT. Domain model covers servicing transfer events, borrower-request intake (modification / assumption / lease) with servicing-standard margin analysis, appraisal ordering with half-open coverage windows, ARA with the 90% appraisal credit and ARA-adjusted P&I advance ceiling, NPV workout scoring across modification / deed-in-lieu / note sale / foreclosure, controlling-class consultation vs consent with the 25% control-termination test, REO with the REMIC 3-year deadline, the seven-step liquidation waterfall, workout/liquidation fee exclusivity, and CREFC-style trustee/rating-agency/certificate-holder reporting.

## §1.8 — 9 rules / 23 instances

`dual_variant_calc` 3, `combinatorial_formula` 3, `non_linear_state_machine` 3, `transitive_cascade` 2, `priority_pair_validation_conflict` 3, `boundary_precision_check` 3, `cross_entity_state_dependency` 2, `resource_temporal_overlap` 2, `compensating_invariant` 2 — every rule ≥2 differentiated instances.

## §1.9 — 9 sections / 68 instances (56 with full `test_recipe`, 12 `excluded_because` stubs)

entities 12, state_machines 15, calculations 12, validations 8, endpoints 6, errors 6, rbac 3, complexity_layers 5, consistency_model 1. All nine claim-extraction-guide sections are present; every `claim_type` comes from the guide's own table rows (no invented categories). All 12 stub citations resolve to real §1.8 instance names in `rule_id / instance_name` form.

## Verification

`scaffold_lint.py` -> **`VERDICT: clean lint`** across 53 endpoints, 13 entities, 23 §1.8 instances, 56 §1.9 recipes, **1,098 API calls** — every call's endpoint, role, payload keys and capture JSONPath conform to §1.5/§1.1, and every FK has reverse-reachability. Instance names are unique across the union of both design files.

Two SCAFFOLD.yaml defects found and fixed while writing §1.9: `ERR_TRANSFER_EVENT_NOT_FOUND` was untriggerable (added `GET /special-servicing/transfer-events/{id}`, 52 -> 53 endpoints), and the `liquidation_proceeds_waterfall` comment cited `ERR_INVALID_REQUEST` where the catalog and validation 32 specify `ERR_LIQUIDATION_EXPENSE_REQUIRED`.

The hard constraint was honored: no sibling `task_*/` directory was listed, globbed, grepped or read at any point.

## Step 3: Copy shared files — 2026-09-03T06:02:26.522Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` -> `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-03T06:17:18.167Z

PRD complete and verified.

**Output:** `workspace/PRD.md` — **485 lines**, written in 11 chunked `cat >>` appends (no single giant Write), ends cleanly on the final row of the §5 error table.

**Section list**
- `# CMBS Special Servicing API — Product Requirements Document`
- `## 1. Introduction`
- `## 2. Global Specifications & System-Wide Principles` — 2.1 Role-Based Access Control · 2.2 API Response Structure (byte-identical, `cat`-ed from the canonical file, incl. `#### Standard Success/Error Response Format`) · 2.3 Pagination · 2.4 Resource Identity, Timestamps and Row Versions · 2.5 The Logical Clock and Date Arithmetic · 2.6 Money, Rates and Rounding · 2.7 Optimistic Concurrency on Parent Aggregates · 2.8 The Order in Which Refusals Are Decided · 2.9 Flat Collections, Foreign-Key Ownership and Reverse Discovery · 2.10 Segregation of Duties · 2.11 Cascades, Compensation and Ledger Consistency
- `## 3. Business Logic & Workflows` — 9 subsections (3.1 Boarding a Trust and Its Loans · 3.2 Two Status Dimensions and the Move into Special Servicing · 3.3 Appraisals · 3.4 Appraisal Reductions, Reduced Advance Obligation, Control Termination · 3.5 Advances and Advance Interest · 3.6 Borrower Requests · 3.7 Workout Alternatives, NPV Testing, Consultation Cycle · 3.8 Disposition, REO and the Liquidation Waterfall · 3.9 Fees, Reporting and the Servicing File)
- `## 4. Endpoint Definitions` — intro + 4-column table
- `## 5. Error Code Catalogue` — 2-column table

**Coverage verified mechanically against SCAFFOLD.yaml**
- Endpoints: **53/53**. Every row matches the scaffold's exact `| METHOD | \`path\` |` and role spellings (tables generated from the YAML, not transcribed). 0 missing.
- Error codes: **45/45**, each with its scaffold `http_status` byte-matched. 0 mismatches.
- Contract 1 (Field-Name Coverage): required union of 168 names (all entity fields + common fields, honouring `ServicingTransferEvent`'s `common_fields: false`, plus all 94 endpoint `input`/`output` identifiers) — **0 missing**, confirmed on two independent passes.
- Contract 2 (Rule Coverage): all **33** priority-ordered validations appear in §2.8 numbered 1–33 with **0** error-id mismatches against the scaffold (including both OCC rules at priority 9); all **13** state machines, their dimensions, initial/terminal states and every state token present; all **64** transitions described (27 in prose rather than arrow notation — spot-checked each); all **13** calculations described including the 3 dual-variant ones with both variant tokens (`GROSS_APPRAISED_BASIS`/`NET_LIQUIDATION_BASIS`, `CONTRACTUAL`/`DELAY_STRESSED`, `STATED_PRINCIPAL`/`ARA_ADJUSTED`); all 7 roles named.
- Contract 3 (§3 Path Purity): **0** backticked paths, **0** bare HTTP methods, **0** occurrences of the `special-servicing` prefix anywhere between `## 3.` and `## 4.`.
- Hygiene: only §2.2's two JSON fences exist in the document (no pseudocode); 0 fuzzy-word hits (`etc.`, `as appropriate`, `as needed`, `TBD`, `and so on`).

Two fixes applied during verification: §2.8 rules 3 and 6 originally referred to the not-found errors generically, leaving all 13 `ERR_*_NOT_FOUND` ids mentioned only in §5; they now name each id explicitly (rule 3 by failing path segment, rule 6 by dangling FK field).

The withheld files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were never opened, grepped, or referenced, and no sibling `task_*/` directory was read. No contract report or audit footer was written into PRD.md.

**Orchestrator truncation check (per the known doc-generator failure mode):** `tail -25` of PRD.md ends on `| \`ERR_DUPLICATE_LOAN_NUMBER\` | 409 |` — a complete final table row at a real section boundary, not mid-sentence. Independently re-counted from the raw file: 53 endpoint rows in §4, 45 `ERR_` rows in §5. Not truncated; no regeneration needed.

## Step 5: Generate unit tests — 2026-09-03T08:15:00.000Z

Generation is complete. 165 tests collect cleanly across both stages.

## Files written

**`test_helpers/` (Stage 1 — 2,145 lines, 9 modules)**
`__init__.py` 15, `types.py` 29, `test_users.py` 105, `api_errors.py` 123, `assertions.py` 197, `constants.py` 238, `api_client.py` 358, `factories.py` 445, `fixtures.py` 635.

**`test_suite/` (Stage 2 — 8,758 lines, conftest + 18 test modules)**

| file | lines | tests |
|---|---|---|
| conftest.py | 16 | — |
| test_01_dual_variant_calculations.py | 408 | 10 |
| test_02_composed_formulas.py | 414 | 10 |
| test_03_non_linear_state_machines.py | 426 | 10 |
| test_04_transitive_cascades.py | 419 | 8 |
| test_05_validation_precedence.py | 299 | 8 |
| test_06_boundary_precision.py | 353 | 9 |
| test_07_cross_entity_gates.py | 236 | 6 |
| test_08_temporal_overlap.py | 399 | 9 |
| test_09_compensating_invariants.py | 511 | 11 |
| test_10_entities.py | 540 | 12 |
| test_11_state_machines.py | 826 | 12 |
| test_12_calculations.py | 735 | 12 |
| test_13_validations.py | 617 | 11 |
| test_14_endpoints.py | 733 | 10 |
| test_15_errors.py | 673 | 12 |
| test_16_rbac.py | 620 | 8 |
| test_17_complexity_layers.py | 369 | 5 |
| test_18_consistency_model.py | 164 | 2 |

## Counts

- **165 tests total** — **Difficulty (queue A) 81**, **Corner (queue B) 84**.
- **79 distinct design instances covered**: all **23** §1.8 difficulty instances (every one with >=2 tests) and all **56** live §1.9 corner instances (entities 12, state_machines 12, calculations 8, validations 6, endpoints 6, errors 6, rbac 3, complexity_layers 2, consistency_model 1).
- The 12 `excluded_because:` corner stubs were not translated (verified mechanically: no stub name appears in any `Design:` tag).

## Skipped instances

**None.** Every non-stub instance passed the PRD-first two-condition filter. Where a recipe's asserted outcome was not uniquely derivable from the PRD, the individual over-reaching probe was dropped rather than the instance — notably: the "committee certifies an absent report" probe in rbac (precedence rule 2 vs. PRD 373 `ERR_ROLE_NOT_PERMITTED_FOR_STATUS` is genuinely ambiguous), and the claim that a `SUPERSEDED` alternative carries no `npv_usd` (PRD 305 runs the arithmetic for every `PROPOSED` alternative, so only `status` and the null `rank` are asserted).

Three recipes were also corrected where they contradicted the PRD before being translated: the rule-11 probe set was re-derived so every (state -> target) pair is itself a declared transition (rule 8 outranks rule 11); `report_type: SPECIAL_SERVICER_LOAN_FILE` was replaced with `DELINQUENT_LOAN_STATUS`; and the uncertified `IMMINENT_DEFAULT` events used to justify a transfer were given `imminent_default_certified: true`, without which the transfer would be `ERR_NO_QUALIFYING_TRANSFER_EVENT`.

## Verification run

`ls -la` + `wc -l` on both directories (above); `ast.parse` over `test_helpers/*.py test_suite/*.py` -> ALL PARSE OK; unused-import scan -> clean; mechanical citation sweep over all 165 tests -> **0 problems** (each docstring ends with exactly one `Design:` line, every tag resolves to a real queue/section/rule_id + instance name, and every citation has a >=9-word fragment surviving a literal grep of `PRD.md`); no `skip`/`skipif`/`xfail` anywhere; no scaffold references leak into the emitted files; `pytest --collect-only` collects 165 tests. `workspace/implementation/` was never read, and no sibling task directory was touched.

## Step 6: Generate implementation — 2026-09-03T08:15:00.000Z

The implementation is complete and verified.

## Files written

`workspace/implementation/`

| lines | file | role |
|---|---|---|
| 60 | `app.py` | app factory, blueprint registration under `/special-servicing`, `ApiError`/`HTTPException` handlers, `app.run(PORT)` |
| 10 | `start.sh` (0775) | launcher; installs Flask only when missing, then `exec python3 app.py` |
| 1 | `requirements.txt` | `flask==3.0.3` |
| 105 | `errors.py` | all 45 error IDs -> HTTP status + default message |
| 45 | `money.py` | `Decimal` helpers, `q2/q4/q6`, ROUND_HALF_UP |
| 142 | `datetimes.py` | logical-clock rendering, calendar/business-day/30-360 arithmetic, EOM clamping, 3 pinned holidays |
| 70 | `db.py` | in-memory `Store` (13 dicts), clock default `2026-08-01T00:00:00.000Z`, `base_row`/`touch` |
| 104 | `response.py` | success/array/error envelopes, pagination, Decimal scrubbing |
| 71 | `middleware.py` | header auth, 7 roles, entity-backed ownership |
| 177 | `validate.py` | rule-5 body validation helpers |
| 186 | `calc.py` | all 13 calculations (3 dual-variant) |
| 458 | `services.py` | lookups, roll-ups, cascades, 7-step liquidation waterfall, write-off |
| 32 | `routing.py` | transition table / system-only-target / target-role / list-filter helpers |
| 462 | `routes_core.py` | trusts, loans, transfer events, asset business plan, both status dimensions, clock (13 endpoints) |
| 552 | `routes_credit.py` | borrower requests, appraisals, reductions, advances (16) |
| 475 | `routes_workout.py` | workout plans, alternatives, consultations + sweep (12) |
| 414 | `routes_disposition.py` | REO assets, fee accruals, distribution reports (12) |

## Endpoint count

**53** — enumerated from Flask's `url_map` and matched one-for-one against the 53 method/path pairs in `SCAFFOLD.yaml` (lines 1819-2299). No extras, no omissions.

## Boot / smoke result

Boots clean from a fresh process (`PORT=<free> bash start.sh`), store empty on every boot (`total_count: 0` for trusts and loans), no disk/SQLite/JSON persistence anywhere, zero seeded rows.

Two scripted end-to-end suites both report **all assertions passed** (status code *and* `error_id` asserted on every refusal):
- Happy path: trust -> loan -> transfer event -> SPECIAL_SERVICING (ABP due +60d) -> appraisal order/receive/accept (SoD enforced) -> provisional ARA `NET_LIQUIDATION_BASIS` 4,780,000.00 / 41.5652% -> EFFECTIVE -> advances with 30/360 interest -> borrower request with servicing-standard analysis -> consultation consent -> APPROVED -> workout plan (OCC 412 verified) -> alternatives scored/ranked -> sweep deems consent after deadline -> APPROVED/EXECUTED -> REO acquire (REMIC +3y) -> fall-through counter -> SOLD waterfall (fee 70,000.00, both advances REIMBURSED, realized loss 5,180,518.06, notional 14,819,481.94 CONTROLLING) -> fee accruals -> distribution report certify/distribute.
- Refusal/edge path: `ERR_APPRAISAL_WINDOW_OVERLAP`, `ERR_LEASE_TERM_OVERLAP`, `ERR_INFO_REQUEST_LIMIT_EXCEEDED`, `ERR_CONSULTATION_WINDOW_CLOSED`, `ERR_STALE_APPRAISAL`, `ERR_NONRECOVERABLE_ADVANCE_OUTSTANDING`, `ERR_ROLE_NOT_PERMITTED_FOR_STATUS` (system-only targets), `ERR_ALTERNATIVE_TYPE_MISMATCH`, `ERR_INSUFFICIENT_TIMELY_PAYMENTS`, `ERR_LIQUIDATION_EXPENSE_REQUIRED`, `ERR_WORKOUT_FEE_NOT_ELIGIBLE`, `ERR_FEE_PERIOD_OVERLAP`, `ERR_FEE_TYPE_CONFLICT`, `ERR_SEGREGATION_OF_DUTIES`, `ERR_NOT_RESOURCE_OWNER`, `ERR_DEPOSIT_BELOW_MINIMUM` (402), `ERR_DUPLICATE_LOAN_NUMBER`, `ERR_STALE_TRUST_VERSION`, plus the OBJECTED->DRAFT revision loop, direct NOTE_SALE liquidation, REO write-off, and the control-termination flip to `CONSULTING_ONLY`.

Two spec deviations found and fixed during verification: `services.consultation_satisfied_for` now treats a `CONSULTATION_ONLY` right as satisfied by any non-`PENDING` resolution (an advisory objection no longer blocks approval), and the waterfall's `LIQUIDATION_FEE` accrual no longer sets the forbidden `collection_amount_usd`.

Read exclusions were honored: `SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`, `test_helpers/`, `test_suite/` and all sibling `task_*/` directories were never opened.

**Orchestrator note:** Steps 5 and 6 were launched concurrently in a single assistant message, so the implementation generator started before `test_suite/` existed on disk — physical isolation from the tests was guaranteed, not merely instructed.

## Step 7: Run tests and iterate — 2026-09-03T08:30:00.000Z

All 8 parallel rounds are green (164/164 each), no `Terminated` in the log, no skip/xfail anywhere.

## Summary

**Iterations run:** 2 (sweep 1 -> 12 consistent + 3 flaky failures; sweep 2 -> 8/8 clean).

**Tests deleted (1):**
- `test_13_validations.py::test_a_borrower_request_carrying_another_variants_field_is_refused` — **conditional-forbiddenness silence**. It asserted `ERR_INVALID_REQUEST` for a `MODIFICATION` carrying `suite_code`, citing only PRD §3.6's *"all four are null for the other two types."* The PRD is explicit with the words **required**/**forbidden** *and* names `ERR_INVALID_REQUEST` at the two genuine variant-guard sites (appraisal `estimated_liquidation_expenses_usd`, fee-accrual period/collection fields) and at the consultation pairing ("must **not** carry"), but does neither for borrower-request variant fields — so a faithful reader may store `null` and ignore the field. The suite's own factories confirm the ambiguity: `modification_request_payload` omits `proposed_maturity_date`, i.e. the identical sentence construction ("A `MODIFICATION` names the ...") is read as *non-enforcing* elsewhere in the same suite. Rule generated from `Corner/validations/conditionally_required_and_conditionally_forbidden_fields_both_enforced` (the appraisal half of that instance is still covered by the surviving tests).

**Assertions removed under STEP 1c partial coverage (2, both in `test_10_entities.py`):**
- `test_boarding_a_trust_returns_the_whole_row_with_its_ledgers_zeroed` and `test_client_supplied_identity_and_ledger_fields_are_not_honoured` each asserted `created_at.startswith("2026-08-01T00:00:00")`, i.e. that `created_at` is minted from the **logical clock**. PRD §2.4 declares only `created_at`'s *format*; §2.5 scopes the logical clock to "every deadline, coverage window, day count, accrual and overdue calculation" and the PRD names the clock explicitly at every field it does stamp from it (`received_on`, `effective_on`, `issued_at`, `scored_on`, `executed_on`, ...) — never for `created_at`. A frozen logical clock would also destroy the `created_at ASC` tie-breaks §2.3 relies on. The millisecond-format assertion was kept; in the second test the assertion was **strengthened toward PRD** rather than dropped, to `assert not created_at.startswith("2020-01-01")` (the client-supplied value is ignored — §2.8 rule 5), which is what that test is actually about.

**Fixes applied to `test_helpers/`:**
- `factories.py` -> `small_controlling_class_trust_payload`: passed `deal_name=`/`original_controlling_class_balance_usd=` positionally-as-kwargs *and* re-splatted `**overrides`, so any caller overriding `deal_name` raised `TypeError: got multiple values for keyword argument 'deal_name'`. Now merges its defaults with `overrides` before delegating to `trust_payload`. (Killed all 6 tests in `test_09_compensating_invariants.py`.)

**Fixes applied to `test_suite/`:**
- `test_15_errors.py::test_an_absent_row_is_answered_before_its_state_or_its_owner_is_considered`: `f.appraisal_received_payload(9000000)` omitted the mandatory `as_of_date` positional -> `TypeError`. Supplied `"2026-08-01T00:00:00Z"`.
- `test_16_rbac.py::test_all_seven_roles_perform_the_operations_reserved_to_them`: drove `CURRENT -> DELINQUENT_60` in one hop, which PRD §3.2 does not declare ("walk the delinquency ladder **one rung at a time**"); the implementation correctly returned `ERR_INVALID_STATE_TRANSITION`. Inserted the `DELINQUENT_30` rung, matching how `test_03` and `test_11` already walk it.

**Fixes applied to `implementation/`:**
- `services.py::recalculate_prior_reductions`: moved the incumbent reduction to `RECALCULATED` but left `advance_reduction_applies` at `True`. PRD §3.3 verbatim: *"it is moved to `RECALCULATED`, its `advance_reduction_applies` is set false"* (reinforced by §3.4: *"that flag is true exactly while the reduction is `EFFECTIVE` and false at every other time"*). Now sets the flag false.

**Flakes triaged, not "fixed":** three `test_11_state_machines.py` tests each failed once in sweep 1 with `RemoteDisconnected` / `ConnectionResetError` at a plain sequential request (`fx.set_clock`), on endpoints with no timing logic and no concurrency in the test. The sweep ran under `setsid` (no `Terminated` in the log, deaths not wall-clock-aligned), and none recurred in any of sweep 2's 8 rounds — load-induced on this contended host, per the runner's own guidance.

**Orchestrator verification (independent of the subagent's report):** all 8 `results.{1..8}.json` re-parsed -> every round `164/164`. `grep` for `mark.skip|mark.xfail|mark.skipif` across `test_suite/` + `test_helpers/` -> **0 hits**. `def test_` count -> **164**, matching the results files. `grep -c Terminated workspace/sweep.log` -> **0**, confirming the sweep ran unreaped under `setsid` and the green result is real rather than an artifact of early death. Final round wall time 322.2s.

## Step 8: Finalize PRD — 2026-09-03T08:34:13.811Z

`PRD_FINALIZED.md` written at `workspace/PRD_FINALIZED.md`.

## Line counts
- `PRD.md`: 485 lines. `PRD_FINALIZED.md`: 485 lines. delta = 0 lines (0.00%). Three in-paragraph revisions only; no sections added; file still ends at the §5 error-catalogue table's last row.

## Changes
- **§2.4 — revise** — pinned that `created_at` and `updated_at` are minted from the server's *real-world* clock, not the logical clock, and that a client-supplied value for either is ignored — `implementation/db.py:53-70` (`base_row` / `touch` both call `wall_now_iso()`), `implementation/datetimes.py:137-142`.
- **§2.5 — revise** — narrowed the blanket "Nothing in this domain is measured against wall-clock time" to *business* measurement, naming the three real-clock values (`created_at`, `updated_at`, `api_request_timestamp`) so §2.5 no longer contradicts the new §2.4 sentence — `implementation/db.py:55,69`, `implementation/response.py:27`.
- **§3.6 — insert** — pinned that the seven type-conditional borrower-request fields are neither mandatory nor conditionally-forbidden: only `loan_id`, `request_type`, `requested_terms_note`, `processing_fee_deposit_usd` are required; an omitted conditional field stores null; a field supplied against the wrong `request_type` is type-checked, then discarded and stored null (no `ERR_INVALID_REQUEST`) — `implementation/routes_credit.py:97-147`.

## Non-edits (Step 7 items that needed no PRD change)
- `recalculate_prior_reductions` flag fix — PRD §3.3/§3.4 already say verbatim that `advance_reduction_applies` goes false outside `EFFECTIVE`; impl now matches (`services.py:314`, corroborated by `services.py:295,434,455`, `routes_core.py:386`, `routes_credit.py:441-443`).
- `test_16` one-hop `CURRENT -> DELINQUENT_60` — PRD §3.2 already enumerates the ladder; `routes_core.py:52-59` refuses it. Pure test bug.
- `factories.py` kwarg collision and `test_15`'s missing `as_of_date` positional — pure fixture bugs; `as_of_date` mandatory on `ORDERED -> RECEIVED` is already PRD §3.3.
- Flaky `RemoteDisconnected` failures — infrastructure, no behavior.

## Pre-edit search log

**Edit 1 (§2.4).** (a) Subject: the clock source of the row-identity timestamps `created_at`/`updated_at`. (b) Enumerated: `grep -rn "created_at"` and `"updated_at|wall_now|base_row("` across all 15 impl modules — every creation path funnels through `db.base_row()` (13 callsites: `routes_core.py:65,150,215`, `routes_credit.py:121,266,474`, `routes_workout.py:82,278,374`, `routes_disposition.py:96,347`, `services.py:280,320`), including `base_row(with_common_fields=False)` for the immutable transfer-event row; every mutation path funnels through `db.touch()`; `datetimes.wall_now` has exactly two consumers (`db.py`, `response.py`); `datetime.now` appears once, inside `wall_now`. All other `created_at` references are sort keys, never assignments. (c) Adjustment: extended the sentence to cover `updated_at` as well as `created_at` — pinning only `created_at` would have left a fresh implementer free to refresh `updated_at` from the logical clock, contradicting `db.py:69`. Deliberately made no claim about the other timestamp fields (`received_on`, `effective_on`, `issued_at`, `scored_on`, `executed_on`, `decided_on`, `collected_on`, `distributed_at`, `calculated_on`, `interest_accrued_through`, `nonrecoverable_determined_on`), which the PRD already sources from the logical clock and the impl stamps via `iso(db.now())`.

**Edit 2 (§2.5).** (a) Subject: the scope of the "no wall-clock" prohibition. (b) Enumerated: same two `wall_now` consumers as above plus a `datetime.now|time.time|utcnow` sweep of the whole package (single hit, `datetimes.py:138`); confirmed `db.Store.now()`/`db.clock` (startup default `2026-08-01T00:00:00.000Z`, `db.py:13,36-43`) is what every business site reads. (c) Adjustment: enumerated the real-clock exceptions exhaustively *and* included `api_request_timestamp` (`response.py:27`) — an off-Step-7 path. Naming only `created_at`/`updated_at` would have implied the envelope timestamp comes from the logical clock, a new mismatch.

**Edit 3 (§3.6).** (a) Subject: borrower-request type-conditional field validation and storage. (b) Enumerated: `grep -rn` for all seven field names plus the internal `_lease_start_dt`/`_lease_end_dt` — writes only at `routes_credit.py:101-145` (intake); reads at `routes_credit.py:167` (`suite_code` list filter), `223-226` (`APPROVED` lease-overlap gate, which tolerates null suite/dates via `_lease_terms_overlap`'s `None` guard at `193-196`), `244-246` (`MODIFICATION` -> `is_modified`); no other module and no update endpoint touches them. Also enumerated every genuine `forbid()` callsite to make sure the "not conditionally-forbidden" claim stays local: `routes_credit.py:327` (appraisal `estimated_liquidation_expenses_usd`) and `routes_disposition.py:220,227-233` (fee-accrual period/collection fields, incl. the `LIQUIDATION_FEE` branch) — all still governed by §2.8 rule 5, plus the consultation pairing check in `routes_workout.py:343-360`. (c) Adjustment: scoped the exemption to "these seven conditional fields" rather than weakening §2.8 rule 5 itself, and kept the "its declared type is still checked" clause because `get_string`/`get_number`/`get_datetime` run at `routes_credit.py:101-109` *before* the variant filter, so a wrongly-typed off-variant value does still raise `ERR_INVALID_REQUEST`.

**Orchestrator verification:** `wc -l` both files -> 485/485; `diff` -> exactly 6 changed lines (3 revised sentences, one per section claimed); `tail -3 PRD_FINALIZED.md` ends on the final `ERR_DUPLICATE_LOAN_NUMBER` table row, i.e. a real section boundary, not truncated.

## Step 9: Complete PRD — 2026-09-03T09:28:03.754Z

**Orchestrator decision (recorded per the autonomy instruction):** Step 9 was run as **three sequential file-partitioned passes** over one in-place `PRD_COMPLETED.md`, rather than as the skill's single full-implementation scan. Rationale: this implementation is ~3,300 lines across 15 modules plus a 113 KB PRD, which is the pipeline's largest single-agent context load and the configuration where a one-shot Step 9 is known to die or silently no-op (leaving `PRD_COMPLETED.md` byte-identical to its step-0 `cp`). Passes were strictly sequential — never concurrent — because all three edit the same file. Each later pass was told the file already existed, was forbidden to re-`cp` or wholesale-overwrite it, and was given the prior passes' coverage so nothing was redone. Cross-partition findings were forwarded as a numbered *must-resolve* list rather than a note.

Partition: **pass 1** app.py, db.py, response.py, middleware.py, validate.py, money.py, datetimes.py, routing.py, errors.py, routes_core.py — **pass 2** routes_credit.py, calc.py — **pass 3** routes_workout.py, routes_disposition.py, services.py.

### Pass 1 — core plumbing (25 changes: 22 ambiguity-pins, 3 mismatch-revisions)
`PRD_FINALIZED.md` 485 lines / 113,048 chars -> `PRD_COMPLETED.md` 485 lines / 120,277 chars (+7,229). Notable: §2.1 whitespace-only headers -> `ERR_UNAUTHENTICATED` and owner checks covering reads while list reads are silently narrowed (`middleware.py:40-67`); §2.2 `api_request_id` = `req_` + 20 upper-alphanumeric (`response.py:20`); §2.3 insertion-order ultimate tie-break (`db.py:59`); §2.4 empty-at-boot store (`db.py:1-6`); §2.6 **mismatch** — six-decimal rounding covers four rate fields while the trust's four rate parameters are stored unrounded (`routes_core.py:80-97`); §2.8 rule 5 explicit-`null`-equals-absent semantics (`validate.py:20-52`); §2.8 rule 11 **mismatch** — system-only `to_status` rejected ahead of rule 8; §3.1 loan **mismatch** — only `original_balance_usd` strictly positive, `current_principal_balance_usd` may be zero (`routes_core.py:136-141`); §5 `ERR_INVALID_REQUEST` also carries 404/405 for transport failures (`app.py:33-44`). All 45 error ids cross-checked against §5 — exact match.

### Pass 2 — credit routes + calculations (24 changes: 19 ambiguity-pins, 5 mismatch-revisions)
120,277 -> 124,410 chars (+4,133), still 485 lines; all 25 pass-1 insertions verified intact. Notable: §2.6 **mismatch** ×2 — the workout fee is the one calculation not consuming trust rates as given (`calc.py:177-181`), and threshold comparisons are not universally on the rounded figure (`routes_credit.py:115`); §3.4 net-basis credit is unfloored so expenses above value give a negative credit (`calc.py:70`), `ara_percentage` = `0.0000` on a zero balance (`calc.py:76-80`); §3.5 **mismatch** — a new advance's `accrued_interest_usd` is *not* zero, it is accrued to the clock with `interest_accrued_through` stamped before the 201 answers (`routes_credit.py:482-492`), and the interest-refresh site list was corrected to active advances only (`services.py:99-117`); §3.6 the `Borrower` ownership test on a body-borne `loan_id` runs before the loan lookup, so a foreign/nonexistent loan yields `ERR_NOT_RESOURCE_OWNER` (`routes_credit.py:111`); §3.7 rank ties beyond `created_at` fall to insertion order, never `id` (`calc.py:138-151`).

Pass 2 forwarded two cross-partition items it could not own.

### Pass 3 — workout + disposition + services (24 changes: 20 ambiguity-pins, 4 mismatch-revisions)
124,410 -> 133,301 chars (+~8,900), still 485 lines; passes 1 and 2 intact (verified by per-line diff attribution — no line inserted, deleted or reordered anywhere in the document).

**Both forwarded items resolved:**
1. **Pass 1's §2.8 rule-11 claim was verified false and re-scoped.** `reject_system_only` is called only at `routes_core.py:339`, `routes_credit.py:206/317/420/526` and `routes_workout.py:150`; `routes_disposition.py` (162, 313, 401) never calls it and runs `require_transition` first, so naming the creation status `ACQUIRED`/`ACCRUED`/`DRAFT` there answers `ERR_INVALID_STATE_TRANSITION` under rule 8. Pass 3 also confirmed no transition table ever targets those creation statuses. Rule 11 now names the six endpoints carrying the exception and carves out the three disposition endpoints explicitly. This is exactly why the last pass is authorized to correct earlier passes' false universals — no later pass existed to catch it.
2. **The unrounded expense-zero guard was pinned.** `routes_disposition.py:171` and `routes_core.py:398` carry the identical `expenses <= 0` compare against the figure as supplied, so a hundredth of a cent clears the guard and is then stored as `0.00`, while the expenses-plus-fee-vs-gross test is on two-decimal figures.

Other notable pass-3 findings: §3.7 **mismatch** — abandonment does not advance the plan to `CONSENT_SATISFIED`; the plan is set `ABANDONED` first and consultations waived after, with no subject cascade (`routes_workout.py:239-251`); §3.7 **mismatch** — plan creation requires `SPECIAL_SERVICING`/`IN_WORKOUT` ahead of the version check and a loan already `IN_WORKOUT` does not move (`routes_workout.py:77-114`); §3.8 **mismatch** — the "no active plan at all" degenerate case is scoped to correction and direct liquidation, REO acquisition being judged on the named `source_workout_plan_id` (`routes_disposition.py:84-93`); §3.4 the `CONTROLLING -> CONSULTING_ONLY` flip drags the consultation downgrade cascade from any caller while the reverse drags nothing (`services.py:204`); waterfall step 6 does not stamp `nonrecoverable_determined_on` unlike §3.5's deliberate determination (`services.py:417`); the write-off cascade's full field-level effects (`services.py:440-459`); §2.7 the two OCC version fields differ — `expected_trust_version` requires minimum 1 so zero/negative is `ERR_INVALID_REQUEST` rather than `ERR_STALE_TRUST_VERSION` (`routes_disposition.py:341`), while `expected_loan_version` is bounded only by integer-ness (`routes_workout.py:74`).

### Totals and orchestrator verification
**73 changes across the three passes (61 ambiguity-pins, 12 mismatch-revisions).** `PRD.md` 485 lines/112,062 chars -> `PRD_FINALIZED.md` 485/113,048 -> `PRD_COMPLETED.md` 485/133,301 (**+20,253 chars, +18.0%, over 64 revised lines**). Verified by the orchestrator: `PRD_COMPLETED.md` is **not** byte-identical to `PRD_FINALIZED.md` (128 diff lines = 64 replacements), so the scan demonstrably ran — checked in bytes rather than lines precisely because correct in-paragraph inserts leave the line count flat; heading count 28 unchanged; tail is still the final `ERR_DUPLICATE_LOAN_NUMBER | 409` §5 table row, not truncated. `implementation/*.py` mtimes all predate Step 8 (latest `services.py` 08:08, the Step 7 fix), confirming Steps 8 and 9 touched documentation only — the green 8/8 x 164/164 sweep therefore still describes the shipped implementation and no re-run was required.

**Pipeline complete.** All nine steps finished; `workspace/PRD_COMPLETED.md` written.
