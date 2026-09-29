# Worklog — task_2335_dairy_digester_renewable_natural_gas

## Step 1: Create task directory — 2026-09-01T00:00:00.000Z

Created `tasks/task_2335_dairy_digester_renewable_natural_gas/` and `tasks/task_2335_dairy_digester_renewable_natural_gas/workspace/` (pre-allocated directory name used verbatim; no index scan performed).

## Step 2: Generate scaffold — 2026-09-01T02:30:00.000Z

All three scaffold artifacts are complete and lint-clean.

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           /home/ubuntu/github/CodingPRD/tasks/task_2335_dairy_digester_renewable_natural_gas/SCAFFOLD.yaml
  Difficulty design:  /home/ubuntu/github/CodingPRD/tasks/task_2335_dairy_digester_renewable_natural_gas/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      /home/ubuntu/github/CodingPRD/tasks/task_2335_dairy_digester_renewable_natural_gas/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    68
  §1.1 entities declared:     12
  §1.8 instances scanned:     21
  §1.9 instances scanned:     61
  Calls scanned (§1.8+§1.9):  996

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

Files (all absolute paths under `/home/ubuntu/github/CodingPRD/tasks/task_2335_dairy_digester_renewable_natural_gas/`):
- `SCAFFOLD.yaml` — §1.0–§1.7 only (no design keys present)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single key `scaffold_difficulty_design`
- `SCAFFOLD_CORNER_DESIGN.yaml` — single key `scaffold_corner_design`

Scaffold content
- Difficulty: `beyond_expert`; archetypes compliance_audit + ledger_reconciliation; layers dual_variant_calculation, cascading_side_effects, rate_threshold_triggers, optimistic_concurrency; parallel state-machine shape; segregation-of-duties role model; immediate consistency.
- 12 entities (Dairy, DigesterFacility, FeedstockAgreement, FeedstockDelivery, OperationsDay, InterconnectAgreement, InjectionNomination, CreditPathway, CreditBatch, VerificationAudit, NutrientApplication, RevenueStatement) with 18 FKs including two self-referential supersede links.
- 68 endpoints, 14 state machines (OperationsDay is a parallel status × gas_state machine), 16 calculations, 43 validations (priority 10→240), 52 errors, 2 OCC concurrency rules, 7 roles.
- Two conserved quantities: MASS_CONTROL (tonnes) and CREDIT_CONTROL (credits), both asserted to zero residual.

Design instances
- §1.8: 21 instances across divergent-variants (3), compound formulas (3), non-linear state machines (2), transitive cascades (2), priority precedence (2), boundary conditions (3), cross-entity dependency (2), range/temporal overlap (2), conservation (2).
- §1.9: 75 instances (61 with executable recipes, 14 `excluded_because` stubs citing §1.8 names) across all nine guide sections — entities 11, state_machines 10, calculations 12, validations 20, endpoints 5, errors 3, rbac 6, cross_cutting_layers 5, consistency_model 3.
- Verified: 96 instance names unique across both files, every stub cites an existing §1.8 name and carries no `test_recipe`, and all 52 error_ids are triggered by at least one non-stub recipe.
- All fixture numbers were pinned by Decimal computation (e.g. certified CI −190.40 → 30.826 LCFS credits / 229654 cents, 1410 D3 RINs / 401850 cents, waterfall postures OPEN 1.253 / RESTRICTED 1.247 / LOCKED 0.613, OLR 1.640–5.467, PAN 4.905/74.065 kg).

## Step 3: Copy shared files — 2026-09-01T02:31:00.000Z

Copied `INSTRUCTION.md` to `tasks/task_2335_dairy_digester_renewable_natural_gas/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-01T02:47:00.000Z

PRD generated at `/home/ubuntu/github/CodingPRD/tasks/task_2335_dairy_digester_renewable_natural_gas/workspace/PRD.md`.

**Size and structure** — 469 lines, ~19k words.

- `# Dairy Digester RNG API — Product Requirements Document`
- **§1 Introduction** (2 paragraphs: the four-business seam, the no-double-recording / no-drift commitment, the divided-authority commitment)
- **§2 Global Specifications & System-Wide Principles**, 11 domain-derived subsections: 2.1 RBAC, 2.2 API Response Structure, 2.3 Pagination and List Filters, 2.4 Common Resource Properties and Version Semantics, 2.5 Numeric Precision/Rounding/Units, 2.6 The Logical Clock, 2.7 Stale-Version Guards on Parent Resources, 2.8 Two Conserved Quantities, 2.9 Request Validation Order, 2.10 The Two Facility Postures, 2.11 Segregation of Duties
- **§3 Business Logic & Workflows**, 9 subsections: master data; contracting manure supply (negotiation loop + service lifecycle); daily intake and organic loading rate; day close / thermal + stability / upset cascade; biogas conditioning; interconnection, nomination windows and injection; digestate separation and nutrient management; credit pathways, batches and annual verification; revenue settlement, dairy shares and the financing covenant
- **§4 Endpoint Definitions** — 4-column table, 68 rows, with a status-code preamble
- **§5 Error Code Catalogue** — 2-column table, 52 rows

**Coverage audit (mechanically verified against SCAFFOLD.yaml)**

- **Contract 1 — Field-Name Coverage: PASS.** 167 `entities[].fields[].name` + 118 endpoint input/query/path identifiers = 195 unique required names; all 195 appear verbatim in backticks. Three passes run: pass 1 surfaced a false-positive class (scaffold marks optional inputs with a trailing `?`), passes 2 and 3 (post-edit) returned an empty diff. No field lists or schema tables — every name reaches the reader through narrative.
- **Contract 2 — Rule Coverage: PASS.** All 69 state-machine transitions across 14 dimensions are described (12 of them via multi-source phrasings such as "accepted from either `ACTIVE` or `SUSPENDED`", verified individually). All 16 calculations rendered with formulas, pinned step order, input sets, variant differences and precision; every named constant appears as a literal except `CI_FLOOR`, deliberately written as "negative 400.00". All 43 validations covered, with the full priority ladder (10→240) rendered as a 27-rank ordered list preserving same-rank groupings, and every `applies_to` endpoint set stated in full (e.g. `ERR_INVALID_DATE_RANGE` across all 6 endpoints; `ERR_PATHWAY_NOT_CERTIFIED` across claim/verify/issue/fieldwork). All 52 error IDs referenced in §1–§3 prose, not just in §5. Both OCC rules, both conserved quantities, all three named cascades (audit-MATERIAL revaluation, upset-curtailment, offspec-nomination-rejection), and every endpoint `side_effects` entry are covered. All enum members of every field appear in backticks.
- **Contract 3 — §3 Path Purity: PASS.** 1,149 backtick tokens in §3 (385 unique); zero start with `/`, zero are bare HTTP methods, zero combine method+path. No stray slash-paths in §3 plain prose either.
- **§2.2** matches `section-2.2-response-structure.md` byte-for-byte (verified by diff), including `req_RANDOMALPHANUM123456`, `2025-05-24T10:30:00.123Z`, `UNIQUE_ERROR_IDENTIFIER_STRING` and `"data": { }`.
- **§4/§5 fidelity:** all 68 endpoints present with exact method+path and no extras; per-endpoint role sets match the scaffold exactly (the single all-seven-role endpoint rendered "All roles"); all 52 error rows match ID and HTTP status in scaffold order.
- **Fidelity sweeps:** no symbolic operators (`==`, `>=`, `min()`, `floor()`, ` IN {`, `+=`, …) anywhere in the document; no fuzzy quantifiers — two glosses ("roughly two-thirds methane", "roughly three weeks") were removed during review even though each followed an exact figure.

Two forbidden files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were never opened, grepped or referenced, and no sibling task directory was read. The three PASS reports live only in this message; nothing was written outside `workspace/PRD.md`.

## Step 5: Generate unit tests — 2026-09-01T05:20:00.000Z

Generation is complete and both verification passes are clean.

## Files created

**`test_helpers/`** (Stage 1 infrastructure, 6 files)
- `test_helpers/__init__.py` — barrel export of framework generics + all helper modules
- `test_helpers/api_client.py` — 68 typed endpoint wrappers over `GenericApiClient`
- `test_helpers/factories.py` — canonical payload builders for all 12 aggregates
- `test_helpers/fixtures.py` — atomic + composite scenario builders (plant, open/closed/pipeline-spec/injected day, certified pathway, claimed/verified/issued batch, separated day, planned application, funded reserve, draft/approved/paid statement, two-dairy variants)
- `test_helpers/test_users.py` — 8 principals x 7 roles + malformed-header builders
- `test_helpers/assertions.py` — common-field and invariant asserters (`assert_mass_control_holds`, `assert_credit_control_holds`)

**`test_suite/`** — `conftest.py` + 14 test modules, `test_01_` ... `test_14_`, grouped by testing concern, every file >=5 tests.

## Test counts

| | tests | distinct instances |
|---|---|---|
| Queue A (§1.8 Difficulty) | **44** | 21 / 21 (every instance >=2 tests) |
| Queue B (§1.9 Corner) | **61** | 61 / 61 non-stub instances |
| **Total** | **105** | |

The 14 `excluded_because:` corner stubs received nothing, as specified (61 + 14 = 75).

## Verification passes (both green)

- **Design-citation pass:** every test has exactly one `Design:` line, positioned last in the docstring; all 105 tags resolve to real instance `name:` values in the correct queue and section/rule_id; zero uncovered non-stub instances; zero untagged or dual-tagged tests. One tag error was found and fixed (`Corner/cross_module/...` -> `Corner/consistency_model/...`).
- **PRD-citation pass:** all 105 `PRD: "..."` quotes verify as verbatim whitespace-normalised substrings of `workspace/PRD.md`; each error-asserting test's citation names the asserted `error_id`.
- No `pytest.skip`/`xfail` anywhere; no mention of the scaffold or scaffold section numbers in generated code; all modules compile; every imported helper name and every `api.<method>` referenced exists.

## Instances skipped

**None.** All 21 difficulty and all 61 non-stub corner instances were implemented.

## Design assertions deliberately omitted (design contradicts the PRD)

Kept as tests, but the specific offending assertion was dropped rather than weakening the test or skipping the instance:

1. `calc_offspec_reason_.../sm_offspec_retest_...` assert `pipeline_gas_scf == 123408.912` on a **failing** conditioning pass; PRD §3.5 forces `pipeline_gas_scf` and `pipeline_gas_mmbtu` to `0.000` on failure — field assertion omitted in both.
2. `endpoint_curtail_decision_...` asserts `delivered_mmbtu == 0.000`; the PRD leaves it null on `CURTAIL` — omitted.
3. `sm_closing_an_already_closed_ops_day_...` asserts day `version == 2`; booking the load also bumps the day version (true value 3) — version assertion omitted.
4. `cm_close_response_...` names `stress_score`; the PRD field is `stress_points` — implemented against `stress_points`.
5. `entity_agreement_creation_stamps_system_fields_and_initial_version` asserts `created_at == 2026-08-01T00:00:00Z`; PRD §2.6 names only three clock-reading behaviours and §2.4 pins only the ISO-8601 three-fractional-digit shape — asserted `created_at == updated_at` + shape instead.
6. `rto_injection_windows_...` had an internal arithmetic error (buffered end 18:30 vs a second window starting 18:00 asserted 201) — emitted as two tests: the verbatim 18:00 collision (409) and a corrected touching-boundary case at 19:00 (201).
7. Five settlement instances say "canonical plant" yet assert zero dairy share and full retention — implemented with facility-only setups so the stated numbers are the PRD-derived ones.

## Step 6: Generate implementation — 2026-09-01T04:55:00.000Z

The implementation is complete and verified.

## Files created

All under `workspace/implementation/`:

**Launcher / deps:** `start.sh` (installs Flask only when missing, then `exec python3 app.py`; honours `$PORT`, default 10000), `requirements.txt` (`Flask==3.0.3`).

**Core:** `app.py` (app factory + `ApiError`/`HTTPException`/catch-all handlers), `config.py` (every pinned literal from the PRD — HHV, BMP, MCF, GWP, CI floor, LCFS/RIN constants, PAN factors, fee tiers, sweep rate, DSCR band, setback days, round ceilings), `errors.py` (all 53 error ids -> status), `response.py` (envelope: `meta`/`response_type`/`data`), `db.py` (in-memory `Store`, 12 dicts, logical clock, `_seq` tiebreaker, `version` bumps), `numeric.py` (`Decimal` helpers, ROUND_HALF_UP / ROUND_FLOOR), `validation.py` (typed body accessors enforcing declared decimal scales + pagination), `middleware.py` (`X-User-ID`/`X-User-Role` auth, role gating, JSON body decode with `parse_float=Decimal`).

**Services:** `services/calc.py` (17 pinned calculations), `services/cascade.py` (10 cascade routines), `services/derive.py` (lazy derived fields + all 12 serialisers).

**Routes:** `routes/` — `common.py` (404 helpers, `resolve_refs`, `paged_list`), plus `admin, dairies, facilities, agreements, deliveries, ops_days, interconnects, nominations, pathways, batches, audits, applications, statements`.

## Endpoint count

**68**, matching SCAFFOLD.yaml exactly (verified against Flask's url_map): clock 1, dairies 3, facilities 6, feedstock-agreements 8, feedstock-deliveries 4, ops-days 7, interconnect-agreements 4, injection-nominations 5, credit-pathways 5, credit-batches 7, verification-audits 7, nutrient-applications 5, revenue-statements 6.

## Notable design decisions

- **Storage** is pure Python dicts, empty on boot — a fresh `GET /dairies` returns `total_count: 0`. No seed/fixture code exists anywhere.
- **Derived fields are computed lazily in serialisers** (dairy counters/status/PAN-YTD, all facility mass-control and revenue-ledger accumulators, all pathway credit totals). Only genuinely stateful values are stored (`reserve_balance_cents`, both postures, `posture_override_active`, `dscr_current`, `design_max_olr`). This makes the MASS_CONTROL and CREDIT_CONTROL residuals structurally zero after every mutation, including cascades and compensating actions.
- **Arithmetic** is `Decimal` end to end; PRD-specified round-then-sum (OLR), floor-then-residual cent allocation, and D3 truncation are honoured. Numbers serialise as `float(quantized)`, money/counters as `int`.
- **Validation ladder**: the full 27-rank global order is implemented, with body-FK resolution (rank 4) deliberately preceding schema validation (rank 6) via `resolve_refs`.
- **Clock separation**: `created_at`/`updated_at` use wall-clock UTC; the logical clock drives only nomination lead time, `signed_at`, and calendar-year nitrogen aggregation.
- Version fields (`expected_pathway_version`/`expected_facility_version`) are rejected with `ERR_INVALID_REQUEST` on endpoints that do not declare them; other unknown body fields are ignored.

## Verification

Three scratch smoke suites (~140 assertions, run out-of-tree in `/tmp`) exercised: full agreement negotiation incl. round exhaustion; delivery gates and OLR recompute on reject; biological-upset cascade (curtailable suspended, firm retained, open-day loads cancelled, closed-day loads preserved, posture override, auto-clear on stable close); off-spec retest cascade (nomination rejection, curtailment counter -> interconnect suspend -> reinstate -> attempts exhausted -> flare -> reopen -> reopen limit); pathway certification and the D3/LCFS credit lifecycle through issue/reverse; the audit chain (fieldwork -> MATERIAL finding -> pathway suspend -> batch revaluation -> DRAFT statement recompute -> remediation -> close -> reinstate); the full settlement waterfall through approve -> pay (with SoD) -> claw-back; and mass-control conservation across separation, application, void and reopen. Every numeric result matched a hand-computed PRD value (fee tiers, DSCR, floor/residual split, CI scores, PAN, digestate mass balance), and all seven initial mismatches traced to arithmetic errors in my scratch expectations, not the implementation — each was re-derived from the PRD text and confirmed correct.

One incidental cleanup: `app.config["JSON_SORT_KEYS"]` (a no-op under Flask 3) was replaced with `app.json.sort_keys = False`, re-verified booting through `start.sh`.

## Step 7: Run tests and iterate — 2026-09-02T07:10:00.000Z

All 8 parallel rounds now pass 105/105.

## Summary

**Iterations run:** 11 full 8-round parallel sweeps (88 round-completions). Final sweep: all 8 rounds `105/105`, `failed 0`, verified directly from `results.1.json` ... `results.8.json`.

**Tests deleted:** none. No test in the suite failed STEP 1a (PRD coverage) or STEP 1b (unique derivability) outright.

**Fixes applied to `test_helpers/`:** none. Audited all of `fixtures.py` (883 lines), `factories.py`, `assertions.py`, `constants.py`, `test_users.py`, `__init__.py` — every composite fixture builds its preconditions through PRD-declared endpoints only. No fixture bug found.

**Fixes applied to `implementation/`:** none. No implementation change proved necessary.

**Fixes applied to `test_suite/`** (one file, `test_suite/test_12_settlement_covenants_and_reserve_ledger.py`):
- `test_08_the_approver_of_a_statement_cannot_release_its_payment` — replaced `assert paid["payment_reference"] == "ACH-2026-08-0002"` with `assert paid["paid_by_user_id"] == USER_FINANCE_B`. Category: **COMPUTED-FIELD SILENCE** (response-field-presence silence), handled per STEP 1c partial-coverage splitting. `payment_reference` occurs exactly once in PRD.md (line 334) and only as a mandatory *request input*; §3.9's enumeration of what payment writes omits it, as does §2.4's common-property list. A faithful PRD-only implementer may validate and discard it, so the assertion failed unique derivability. `paid_by_user_id` is verbatim PRD-required ("Payment writes the acting `X-User-ID` into `paid_by_user_id`"), so the substitution makes the test strictly more faithful. All other assertions were preserved, including the SoD `403 ERR_SEGREGATION_OF_DUTIES` check that is the test's actual subject.
- Same file: added the `USER_FINANCE_B` import that substitution required (fixing a `NameError` the first edit introduced).

**Key findings**

The dominant obstacle was host infrastructure, not the task artifacts. 100% of non-passing results in every sweep traced to two runner-side signatures: `subprocess.TimeoutExpired` on the runner's unconditional `lsof -ti:PORT -sTCP:LISTEN` call (hard `timeout=5` in `prd-bench-local-runner/src/prd_bench_local_runner/pytest_plugin.py::_kill_port`, invoked before every per-test restart regardless of how cleanly the app exits), plus occasional `ConnectionResetError` / pytest-timeout-on-setup from servers reaped mid-request. Because `test_suite/conftest.py` fixtures perform zero I/O, any "failed on setup" is by construction the runner's own restart fixture. Pass counts tracked host load almost perfectly — 22-31/105 at load ~440, rising monotonically to 105/105 at load ~99 with no artifact changes in between — which is what identified the cause. Up to 313 concurrent `prd-bench-local-run` pipelines from other users were on the box; I resolved it by scheduling sweeps into low-load windows rather than by touching the harness.

I also specifically audited the constructs that could produce genuine flakiness and found none: every `sort`/`sorted` in the implementation carries a deterministic `(_created, _seq)` tiebreaker, and the logical clock is read in exactly the three places PRD §2.6 names (nomination lead-time check, `signed_at`, PAN calendar-year window), with no wall-clock fallback. Storage is confirmed in-memory only — no `sqlite3`, file `open(`, `json.dump`, `pickle`, or `/tmp` use anywhere in `workspace/implementation/`.

One numeric disagreement worth noting: my hand arithmetic for `credit_quantity_final` gave 30.827 / CI -190.41 against the test's 30.826 / -190.40. Rather than "fix" the test to match my math, I executed `services.calc` directly and it reproduced the test's values exactly (`qty 30.826`, `val 229654`). The test was right and my hand calculation was wrong — no change made.

## Step 8: Finalize PRD — 2026-09-02T07:15:00.000Z

`workspace/PRD_FINALIZED.md` written: a copy of `PRD.md` with exactly one in-line revision.

## Line counts
- `PRD.md`: 468 lines — `PRD_FINALIZED.md`: 468 lines — **0.00% line delta** (single-line in-place revision, +176 chars).

## Changes
- **§3.9 (Revenue Settlement, line 334)** — *revise* — the `payment_reference` clause now states that the server validates it as a required string but does not retain it (written to no statement field, absent from the response body) — `implementation/routes/statements.py:121` (validated via `b.string("payment_reference")`, value never assigned) and `implementation/services/derive.py:474-509` (`ser_statement` omits it).

## Per-edit pre-edit search log

**Edit 1 — §3.9 `payment_reference`**

(a) **Subject identified:** the lifecycle of the `payment_reference` request input on `POST /revenue-statements/{id}/pay` — its validation strictness and whether it is persisted on / serialized from the `RevenueStatement`.

(b) **Impl paths enumerated (read/grepped):**
- `grep -rn "payment_reference" --include=*.py workspace/` -> exactly one hit, `routes/statements.py:121`; no service, cascade, derive, filter, or fixture path touches it.
- `routes/statements.py:116-140` (`pay_statement`) — read in full: `b.string("payment_reference")` return value is discarded; only `status` and `paid_by_user_id` are written to the statement, plus `facility["reserve_balance_cents"]`.
- `routes/statements.py:41-61` (`create_statement`, the only place a statement row is minted) — the row dict has no `payment_reference` key, so the field can never exist on the row.
- `services/derive.py:474-509` (`ser_statement`) — the single serializer used by create/list/read/approve/pay/claw-back; key set confirmed to exclude `payment_reference`.
- `routes/statements.py:81-91` — list/read reuse `ser_statement`; the list filter tuple is `("facility_id","status","superseded_by_statement_id")`, so no filter path exposes it either.
- `validation.py:13-48` (`Body.__init__`, `Body.string`) and `middleware.py:39-49` (`body()`) — confirmed `string()` requires presence, non-null, `str` type and non-blank, and that unknown body keys are silently ignored (only `VERSION_FIELDS` are rejected), so "validates as a required string" is accurate and no unrelated strictness claim is implied.
- Parallel-endpoint sweep for the same "free-text input" subject to be sure the new sentence does not imply anything false elsewhere: `grep` for `signatory_name`, `applicator_name`, `memo`, `cover_note`, `comment`, `claim_note`, `verifier_note`, `issuance_reference`, `approval_note`, `narrative`, `closing_note`, `remediation_plan`, `void_reason`, `claw_back_reason`, `justification` -> all are likewise validated-and-discarded (single hit each, in a route, never stored), while enum-valued `rejection_reason`/`reversal_reason`/`suspension_reason` *are* stored. This is why the sentence was kept scoped to `payment_reference` only rather than generalized.

(c) **Wording adjustment made:** two. (1) Dropped an earlier draft's "non-blank" qualifier — accurate for the impl but a strictness pin not traced to the Step 7 item, and asserting it for one field while PRD is silent for the ~15 sibling free-text fields would have read as a contrast that the impl does not exhibit. (2) Rejected a generalized phrasing ("like the other notes and references accepted by action endpoints...") because it would have swept in `rejection_reason`, `reversal_reason` and `suspension_reason`, which the impl *does* persist — a false universal. Final wording is scoped strictly to `payment_reference` and says nothing about any other field.

## Notes
- No other PRD edit was made: the Step 7 diff records zero implementation fixes, zero test deletions, zero `test_helpers/` fixes, and only the one `payment_reference` -> `paid_by_user_id` assertion substitution (plus its `USER_FINANCE_B` import, a pure test-mechanics fix with no PRD implication).
- Incidental observation, deliberately **not** patched (out of the Step 7 scope): §3.9 says payment "increases the facility's `dairy_share_paid_cents` ... and `retained_to_date_cents`", whereas `pay_statement` mutates only `reserve_balance_cents` and those two figures are recomputed from `PAID` statements in `derive`/`cascade` — behaviourally equivalent and already covered by §3.36's closing sentence, so PRD prose was left verbatim.

## Step 9: Complete PRD — 2026-09-02T07:45:00.000Z

All edits are complete and verified.

## File deltas

| | lines | chars |
|---|---|---|
| `PRD_FINALIZED.md` (source) | 468 | 101,432 |
| `PRD_COMPLETED.md` | 473 | 120,532 |
| **delta** | **+5** | **+19,100** |

The +5 lines are the only three pure additions (one bullet in §2.2, one paragraph in §2.4, one paragraph in §2.5); the other 46 changes are in-place rewrites of existing sentences. A heading-level diff confirms all 21 headings unchanged — no section added, removed or renamed.

## Counts

- **49 changes total** across 49 diff hunks
- **37 ambiguity-pins** (PRD was silent; minimal inline prose inserted)
- **12 mismatch-revisions** (PRD asserted behaviour the implementation does not exhibit)

## Change log

- §2.1 — insert — ambiguity — a present-but-blank/whitespace `X-User-ID` is a 401, not just an absent header — `middleware.py:25`
- §2.2 — revise — ambiguity — `api_request_id` is `req_` + exactly 20 chars from `A`-`Z`/`0`-`9` (24 total), freshly generated per response — `response.py:8,12`
- §2.2 — insert — ambiguity — new bullet: `ERR_NOT_FOUND`/`ERR_METHOD_NOT_ALLOWED`/`ERR_INTERNAL` are the only IDs outside §5, are decided by routing so precede the §2.9 ladder, and trailing slashes are insignificant — `app.py:44-60`, `app.py:36`
- §2.3 — insert — ambiguity — `has_more` = `offset + len(page) < total_count`; limit 1-100, offset >= 0, non-integer -> `ERR_INVALID_REQUEST`, empty string -> default; and `created_at` ties everywhere resolve by insertion order, never by `id` — `response.py:42`, `validation.py:170`, `db.py:95`
- §2.3 — insert — ambiguity — filters are exact string compares on the serialised field, empty-string filters ignored, null fields match nothing, filtering precedes the page window so `total_count` counts the filtered set — `routes/common.py:80-81`
- §2.4 — insert — ambiguity — new paragraph: all 17 free-text note/reason/justification fields are validated then discarded (write-only); only a batch's `reversal_reason` persists — `routes/*.py` (e.g. `agreements.py:129`, `statements.py:123`)
- §2.5 — insert — ambiguity — new paragraph: scales govern computation, not rendering; non-monetary values are JSON numbers so trailing zeros vanish (`3.500` -> `3.5`); money is integer JSON; nulls are JSON `null` — `numeric.py:30`
- §2.8 — insert — ambiguity — the two invariant read endpoints return the whole facility / whole pathway representation, not a reduced projection — `routes/facilities.py:66`, `routes/pathways.py:52`
- §2.9 rank 4 — insert — ambiguity — FK resolution happens only for non-empty string values; absent/null/blank/non-string keys fall through to the rank-6 schema check, so a later bad FK's 404 can precede a missing FK's 400 — `routes/common.py:49-58`
- §2.9 rank 6 — insert — ambiguity — empty/whitespace body reads as `{}`; malformed JSON is itself `ERR_INVALID_REQUEST`; numbers decode as exact decimals; unnamed properties ignored (except the two version fields); typing strict and explicit `null` counts as absence — `middleware.py:39-48`, `validation.py:13-133`
- §2.9 rank 10 — **revise** — **mismatch** — reversed the stated precedence: every rank-10 specific state error concerns a *related* row or a non-`status` flag, and each route tests its own target's from-state first, so generic `ERR_INVALID_STATE` is what surfaces when both would fire — `routes/nominations.py:122-128`, `routes/audits.py:98-100`
- §2.10 — insert — ambiguity — an override whose named dimension is not in the exact from-state is `ERR_INVALID_STATE` (409), after the enum/justification schema check — `routes/facilities.py:88-99`
- §2.10 — **revise** — **mismatch** — the override flag clears only when a recomputation *actually moves* `distribution_posture` to `OPEN`; a recomputation leaving an already-`OPEN` posture clears nothing — `services/derive.py:185-189`
- §3.1 — insert — ambiguity — creation validates in the order the fields are named; `digester_volume_m3` is the one unscaled quantity and `target_temperature_c` has no range bound (sub-zero accepted) — `routes/facilities.py:24,27`
- §3.2 — insert — ambiguity — offer's two conditions are both `ERR_INVALID_STATE`; the transition touches nothing but the agreement; counter bounds given, with `countered_revenue_share_pct` deliberately uncapped while revision re-applies the 0.95 cap — `routes/agreements.py:73-77,91,112`
- §3.2 — insert — ambiguity — reinstating into an upset facility is `ERR_INVALID_STATE`, not `ERR_FACILITY_UPSET` — `routes/agreements.py:159`
- §3.2 — **revise** — **mismatch** — TERMINATE re-derives the dairy `status` from the resulting counters by §3.1's rules (so `PROSPECT` only when the contracted count is genuinely zero) rather than asserting the count has reached zero; agreement and dairy `version` each +1; no delivery sweep — `routes/agreements.py:166-172`, `services/derive.py` (`dairy_status`)
- §3.3 — insert — ambiguity — booking consults neither the receiving day's `status` (a `CLOSED` day accepts loads) nor the agreement's own `facility_id` — `routes/deliveries.py:22-78`
- §3.3 — insert — ambiguity — rejection's two conditions are both `ERR_INVALID_STATE`, delivery status tested before day status — `routes/deliveries.py:100-102`
- §3.4 — **revise** — **mismatch** — corrected the close gate order: `OPEN`, then >=1 `ACCEPTED` delivery (both `ERR_INVALID_STATE`), then the upset gate last; plus the bounds on all nine submitted readings — `routes/ops_days.py:99-104,86-96`
- §3.4 — **revise** — **mismatch** — the digestate rewind is only partial: the three separation *inputs* (`solids_capture_pct`, `bedding_recovery_pct`, `lab_total_nitrogen_mg_per_l`) survive a reopen, as do all raw-gas and stability fields, and `ops_posture` is not re-derived; the four reopen preconditions are ordered `ERR_INVALID_STATE` checks ahead of the ceiling — `routes/ops_days.py:165-197`, `ops_days.py:42-47`
- §3.5 — insert — ambiguity — the four treated readings are mandatory with stated bounds; a `FLARE` pass carries none of them, needs no interconnect, ignores and does not increment `conditioning_attempts`, and bumps only the day's `version`; interconnect checked before the attempt ceiling — `routes/ops_days.py:210-233`
- §3.5 — **revise** — **mismatch** — off-spec curtailment counts are tallied per interconnection agreement (each charged only for nominations naming it), every touched agreement's `version` +1 regardless, and suspension fires when the count *reaches or passes* three on an agreement *still* `ACTIVE` — `services/cascade.py:127-143`
- §3.5 — insert — ambiguity — the flare zeroes the two pipeline figures but leaves the four `treated_` readings, `pipeline_hhv_btu_per_scf` and `offspec_reason` intact — `routes/ops_days.py:222-231`
- §3.6 — **revise** — **mismatch** — nomination requires the *named* `interconnect_id` itself to be `ACTIVE` (not merely that some active agreement exists); plus both window bounds are ISO-8601 strings compared in UTC but stored and echoed verbatim — `routes/nominations.py:29-40,76`
- §3.6 — insert — ambiguity — lead-time equality passes (and `nomination_lead_hours` 0 allows a window at the clock instant); `window_minutes` truncates down and a zero-minute window is `ERR_HOURLY_CAPACITY_EXCEEDED` before any division — `routes/nominations.py:44,64-66`
- §3.6 — **revise** — **mismatch** — `CONFIRM`'s non-active interconnect is `ERR_INVALID_STATE` (not `ERR_NO_ACTIVE_INTERCONNECT`); out-of-band `curtailed_mmbtu` is `ERR_INVALID_REQUEST`; `CURTAIL` checks nothing but the from-state; suspension needs count >= 3 on a still-`ACTIVE` agreement and both rows' `version` +1 — `routes/nominations.py:113-128`, `services/cascade.py:146-151`
- §3.6 — insert — ambiguity — `delivered_mmbtu` is zero-or-more at 3 dp (a failed injection is 0.000); delivery does not require the interconnect to still be `ACTIVE`; the three checks run from-state -> `gas_state` -> confirmed ceiling — `routes/nominations.py:147-158`
- §3.6 — insert — ambiguity — `TERMINATE` from `SUSPENDED` skips the live-commitment check entirely, and all three interconnect status-change preconditions report `ERR_INVALID_STATE` — `routes/interconnects.py:61-75`
- §3.7 — insert — ambiguity — all three separation inputs mandatory with bounds, and the operation inspects nothing about the day but `separation_recorded` (any `status`, any `gas_state`) — `routes/ops_days.py:269-285`
- §3.7 — insert — ambiguity — a null `lab_total_nitrogen_mg_per_l` is read as zero at planning time (not rejected), and corrected by the commit-time recomputation — `services/calc.py:158`
- §3.7 — insert — ambiguity — the four commit preconditions are evaluated in the stated order, preceded by the application's own `PLANNED` from-state check (`ERR_INVALID_STATE`) — `routes/applications.py:104`
- §3.7 — insert — ambiguity — voiding from `PLANNED` bumps only the application's `version` (facility and dairy untouched); any other state is `ERR_INVALID_STATE` — `routes/applications.py:137`
- §3.8 — insert — ambiguity — CERTIFY's two conditions are ordered `ERR_INVALID_STATE` checks after the reference dates are parsed and range-checked — `routes/pathways.py:69-71`
- §3.8 — insert — ambiguity — a zero energy denominator is guarded: raw avoidance and transport intensity are both taken as 0.00 — `services/calc.py:111`
- §3.8 — insert — ambiguity — batch creation's mismatch and overlap checks run in that order, both after the stale-version guard — `routes/batches.py:32-41`
- §3.8 — insert — ambiguity — the claim's rejection keys on set *emptiness*, not on the sum: `DELIVERED` nominations all at 0.000 still claim successfully — `routes/batches.py:110-117`
- §3.8 — insert — ambiguity — reversal's statement tail: containment spelled out, statements swept in `created_at` order each +1 version, and the facility's `version` bumps only if `distribution_posture` actually moved (nothing re-derived when there is no driving statement) — `services/cascade.py:63-86`, `services/derive.py:193`
- §3.8 — insert — ambiguity — `audit_year` is a required integer > 0 unrelated to the clock's year; all six actuals mandatory and zero-or-more at their §2.5 scales — `routes/audits.py:36-45`
- §3.8 — insert — ambiguity — findings on an audit with no recorded fieldwork is `ERR_INVALID_STATE` (same code as the wrong-from-state check), from-state tested first — `routes/audits.py:98-100`
- §3.8 — **revise** — **mismatch** — the `MATERIAL` move to `SUSPENDED` is conditional on the pathway being `CERTIFIED` at that instant, and the pathway's `version` increments on **all three** severities, not only `MATERIAL` — `routes/audits.py:114-116`
- §3.8 — insert — ambiguity — a still-null `finding_severity` also blocks remediation; the three checks fire from-state -> severity -> round ceiling; both close-time rejections are `ERR_INVALID_STATE` — `routes/audits.py:130-132,151-154`
- §3.8 — insert — ambiguity — pathway REINSTATE/REVOKE precondition violations are `ERR_INVALID_STATE`; REVOKE reverses in `created_at` order, bumps each batch and the pathway, and deliberately recomputes **no** revenue statement — `routes/pathways.py:80-98`
- §3.9 — insert — ambiguity — the statement-period overlap test runs after the stale-version guard — `routes/statements.py:29-38`
- §3.9 — insert — ambiguity — a negative residual pool is clamped to zero, and no line takes more than one residual cent, so a surplus pool goes undistributed — `services/calc.py:211-214`
- §3.9 — **revise** — **mismatch** — statement creation bumps the facility's `version` by one, and by one *more* (two total) only when the covenant test actually moved `distribution_posture` — `routes/statements.py:75-77`
- §3.9 — insert — ambiguity — payment neither recomputes the waterfall nor re-derives `dscr_current`/`distribution_posture` — `routes/statements.py:136-139`
- §3.9 — **revise** — **mismatch** — claw-back bumps the facility's `version` by one for the ledger movement plus one more only if the re-derivation moved the posture, and leaves both covenant figures where they were if no driving statement remains — `routes/statements.py:157-159`, `services/derive.py:193`
- §4 `/_clock/set_current_utc` — insert — ambiguity — takes a mandatory `to_iso8601` string, `ERR_INVALID_REQUEST` on unparseable input, returns an empty `data` object — `routes/admin.py:14-20`
- §4 `/feedstock-deliveries` — **revise** — **mismatch** — "on an open operations day" corrected to "onto a named operations day, whose own `status` is not consulted" — `routes/deliveries.py:22-78`
