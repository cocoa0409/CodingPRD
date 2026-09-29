# Worklog — task_2604_trade_finance_letter_of_credit_issuance

## Step 1: Create task directory — 2026-09-03T18:24:31.893Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2604_trade_finance_letter_of_credit_issuance` and `.../workspace`. Index 2604 was pre-assigned by the orchestrator invocation; no auto-allocation scan performed (32 concurrent pipelines on this host).

## Step 2: Generate scaffold — 2026-09-03T20:47:45.674Z

All three scaffold artifacts are complete and the linter is clean.

**Output directory:** `/home/ubuntu/github/CodingPRD/tasks/task_2604_trade_finance_letter_of_credit_issuance/`

| file | lines | bytes | top-level key(s) |
|---|---|---|---|
| `SCAFFOLD.yaml` | 3415 | 203301 | scenario, domain_name, api_prefix, complexity_profile, response_envelope, entities, state_machines, concurrency_rules, calculations, validations, endpoints, errors, roles (no design keys) |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 2571 | 165481 | `scaffold_difficulty_design` only |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 7881 | 495223 | `scaffold_corner_design` only |

Each tail ends at a real structural boundary (a final `assert` list item / the final `shared_operations: []` RBAC key), and all three `yaml.safe_load` cleanly.

**Lint verdict (verbatim, final run):**
```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           tasks/task_2604_trade_finance_letter_of_credit_issuance/SCAFFOLD.yaml
  Difficulty design:  tasks/task_2604_trade_finance_letter_of_credit_issuance/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      tasks/task_2604_trade_finance_letter_of_credit_issuance/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    53
  §1.1 entities declared:     14
  §1.8 instances scanned:     18
  §1.9 instances scanned:     73
  Calls scanned (§1.8+§1.9):  1525

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

**§1.0–§1.7 counts:** 14 entities, 10 state machines, 2 OCC concurrency rules, 13 calculations, 37 ordered validations, 53 endpoints, 68 errors, 8 roles. Profile: `compliance_audit` / `multi_party_negotiation`, layers `[optimistic_concurrency, cascading_side_effects, dual_variant_calculation, selector_policy, ops_run_checkpoint]`, graph topology, cyclic state machines, `segregation_of_duties`, `immediate` consistency, `difficulty_level: expert_plus`.

**§1.8 — 9 rule_ids × 2 instances = 18:** `dual_variant_calc`, `combinatorial_formula`, `non_linear_state_machine`, `transitive_cascade`, `priority_pair_validation_conflict`, `boundary_precision_check`, `cross_entity_state_dependency`, `resource_temporal_overlap`, `compensating_invariant`.

**§1.9 — all nine guide sections, 86 instances (73 full recipes + 13 `excluded_because` stubs):** entities 13, state_machines 14, calculations 20, validations 11, endpoints 7, errors 6, rbac 7, cross_cutting_complexity_layers 6, consistency_model 2. All 104 instance names are unique across the union of both design files. Both §1.2.1 OCC rules (`expected_credit_version` on amendment create, `expected_facility_version` on collateral posting) are covered under `optimistic_concurrency`, each with `${...}` version values.

**Error coverage:** a programmatic check of all 68 §1.6 `error_id`s against the text of both design files returns zero uncovered.

**Design adjudications:**
- 53 endpoints / 68 errors exceed the Expert bands (20–32 / 18–30). Justified by the nine distinct workflows named in the scenario plus the explicit "harder than expert level" instruction; recorded as `difficulty_level: expert_plus` with an explanatory comment above §1.6. Entities held at 14 (top of the Expert band) to keep the graph legible.
- Error triggerability was concentrated into 6 multi-trigger `errors` instances rather than ~30 thin ones: guide Table 6 only demands that every code be triggerable, and error-envelope captures put those instances in the lint's negative-trigger class.
- Guide Tables 6 and 7 carry no row labels for the per-code / per-role claims, so `error_triggerable`, `unauthenticated_request`, `unauthorized_operation`, `segregation_of_duties`, `principal_scoping`, `shared_operations`, `exclusive_operations` were authored; cross-cutting instances use the layer name as `claim_type` where the guide has no row (`selector_policy`, `ops_run_checkpoint`).
- Two structural fixes forced by the linter/spec this session: added `GET /presentations/{id}/screenings` → `ScreeningCheck[]` to §1.5 to give `ScreeningCheck.presentation_id` reverse-reachability (the `/credits`-rooted filtered list did not satisfy the collection-path rule), and inserted the missing `POST /presentations/{id}/conclude-examination` hop in the sweep-checkpoint recipe since waiver requests require `examination_status == DISCREPANT`.
- YAML anchors/aliases deliberately avoided so every `setup_api_calls` entry is directly transcribable by a downstream generator; the `$.data[N].field` JSONPaths are quoted to avoid the flow-mapping parse error.

## Step 3: Copy shared files — 2026-09-03T20:48:06.401Z

Copied `./INSTRUCTION.md` to `tasks/task_2604_trade_finance_letter_of_credit_issuance/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-03T21:22:00.000Z

PRD generation complete.

**Output:** `.../workspace/PRD.md` — **515 lines / 119,200 bytes**, built incrementally (1 `Write` + 8 heredoc appends + 2 targeted edits), ending cleanly at the last row of the §5 error table.

**Section list**
- §1 Introduction
- §2 Global Specifications & System-Wide Principles — 2.1 Principals, Roles and Ownership · 2.2 API Response Structure (verbatim block) · 2.3 Pagination and List Ordering · 2.4 Instrument Records, Versions and Timestamps · 2.5 The Logical Clock and Deterministic Date Arithmetic · 2.6 Minor Units, Rounding and Ledger Conservation · 2.7 Path Resolution and Reference Integrity · 2.8 Optimistic Concurrency Control on Credits and Facilities · 2.9 The Order of Rejection · 2.10 Segregation of Duties · 2.11 Window and Interval Conventions
- §3 Business Logic & Workflows — 3.1 Parties, Facilities and Collateral · 3.2 Drafting a Documentary Credit · 3.3 Approval, Issuance and the Facility Exposure Cascade · 3.4 Confirmation and the Confirming-Line Window · 3.5 Amendment Negotiation and Beneficiary Consent · 3.6 Presentation of Documents and the Examination Period · 3.7 Discrepancies, Waiver Requests, Refusal and Preclusion · 3.8 Sanctions and Dual-Use Screening · 3.9 Settlement, Reimbursement and the Clock-Driven Sweep
- §4 Endpoint Definitions (4-column table, 53 rows)
- §5 Error Code Catalogue (2-column table, 68 rows)

**Coverage documented:** 53 endpoints (21 GET, 31 POST, 1 PATCH) · 68 errors · 37 validations · 13 calculations · 10 state machines (60 transitions) · 14 entities (141 fields) · 8 roles.

Field coverage check: entities 141/141, request_body 84/84, query_params 25/25 — PASS.
Rule coverage check: validations 37/37, OCC 2/2, transitions 60/60, calculations 13/13, side_effects 53/53, entity fields 141/141, sibling-branch symmetry 10/10 — PASS.
Path purity check (§3 only): 1425 backtick tokens scanned, 0 leading-`/` tokens, 0 bare HTTP-method tokens — PASS.

Notes: `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` were never opened, grepped or referenced. No difficulty/benchmark meta-commentary appears (verified zero hits for "expert", "benchmark", "difficulty", "harder than", "§1.8", "§1.9", "test_recipe"). One scaffold inconsistency was reconciled conservatively: the ISSUED→CANCELLED guard is stated two ways (state machine ledger test vs. endpoint live-presentation test), so §3.3 requires both, mapped to `ERR_CREDIT_HAS_LIVE_PRESENTATION` (409).

**Orchestrator anti-truncation verification:** independently confirmed — `tail` ends at the final `ERR_COLLATERAL_RELEASE_BLOCKED | 422` table row (a real section boundary, not mid-sentence); all 5 top-level sections and 11 §2 + 9 §3 subsections present.

## Step 6: Generate implementation — 2026-09-03T22:14:00.000Z

The implementation is complete, smoke-tested end-to-end, and the smoke server was killed by its exact PID (2138186, port 39203 confirmed free).

## Files — `tasks/task_2604_trade_finance_letter_of_credit_issuance/workspace/implementation/`

| file | lines | contents |
|---|---|---|
| `start.sh` | 10 | reads `$PORT`, installs Flask only when missing, `exec python3 app.py` (foreground). **Now `chmod +x`** — it was non-executable, which would have failed every harness boot |
| `app.py` | 75 | blueprint registration, `ApiError` handler, 400/404/405/415/500 mapped into the envelope, binds `0.0.0.0:$PORT`. No seeding |
| `db.py` | 175 | in-memory `Store` (14 dicts), logical clock from `2026-08-01T00:00:00Z`, `new_row`/`touch`/`public`/`snapshot`/`restore` |
| `errors.py` | 97 | all 68 error ids → (status, message) |
| `response.py` | 84 | PRD §2.2 envelope, `req_`-prefixed `api_request_id`, pagination 10/1/100/0 |
| `middleware.py` | 128 | 8 roles, ownership, SoD, deferred-404 `pending()` |
| `validate.py` | 277 | shape layer; every failure is `ERR_INVALID_REQUEST` |
| `calc.py` | 636 | all 13 calculations (floor-div exposure vs half-up charges kept strictly apart) |
| `ledger.py` | 361 | pure-aggregation ledgers + the 4-hop cascades |
| `routes_parties.py` | 341 | 15 endpoints |
| `routes_credits.py` | 635 | 14 endpoints |
| `routes_amendments.py` | 289 | 3 endpoints |
| `routes_presentations.py` | 642 | 12 endpoints |
| `routes_settlement.py` | 196 | 2 endpoints |
| `routes_ops.py` | 233 | 2 endpoints (clock + 5-pass sweep) |

4,180 lines total. `pyflakes` clean; no TODO/stub/`NotImplementedError`; no file, sqlite or `/tmp` persistence.

## Coverage (machine-verified against SCAFFOLD.yaml)
- **53/53 endpoints** — set-equality diff of Flask's url_map against the scaffold: no missing, no extra.
- **68/68 errors** — every catalogued id is referenced by live code (plus 3 non-catalogued framework fallbacks: `ERR_NOT_FOUND`, `ERR_METHOD_NOT_ALLOWED`, `ERR_INTERNAL`).
- **37/37 validations**, each reachable via its declared error.
- **13/13 calculations**, **10/10 state machines** (both `DocumentaryCredit` dimensions, both `Presentation` dimensions).

## Smoke evidence (4 scripts, each on a fresh boot)
Sight flow: issue → allocation OPEN 8,400,000 + charge 25,000 → present → discrepancy → waiver GRANT → COMPLYING → PAYMENT claim → net 9,480,350 (commission 11,400, doc fee 4,750+3,500). Usance flow: gross 20,150,000 with tenor add-on, amendment OCC 412 → SoD 403 → auto-ACCEPTED (increase needs no consent) → cooling-off `ERR_AMENDMENT_WINDOW_CONFLICT` → HIT_PENDING_REVIEW → ESCALATE blocks lodging → rescreen+RELEASE → ACCEPTANCE net 19,718,000 (discount 225,000 over 90 days) → sweep ACCEPTED→MATURED → REIMBURSEMENT priced as sight honour, net 19,959,000. Facility flow: 95% breach → SUSPENDED + sibling ON_HOLD → sweep releases → `facilities_reactivated: 1` + sibling back to APPROVED. Sweep is idempotent (second run all zeros) and `dry_run` reports identical counters while mutating nothing. Conservation verified: cancel/expiry restore the facility to exactly 0 allocated.

## PRD ambiguities resolved
1. **Band 3 ordering vs. band-2 ownership.** §2.9 says "shape, **then** existence", but a 403 ownership check needs the row. Resolution: resolve the row silently, run the 403, run payload shape validation, and only then raise the deferred 404. I reordered five handlers (`approve`, `confirmation-responses`, `amendments/{id}/issue`, `consent`, `waiver respond`, `documents`, `submit`, `screening review`) that had 404 firing before shape.
2. **`POST /credits/{id}/approve` from a wrong state** has no declared error. Used `ERR_CREDIT_NOT_DRAFT` (409); state required is `PENDING_CREDIT_APPROVAL`.
3. **`confirmation-requests` on a wrong `confirmation_status`** has no dedicated error → `ERR_CREDIT_NOT_ISSUED` (409).
4. **`settle` when the presentation is not at `CLAIM_LODGED`** has no declared error → reused `ERR_CLAIM_NOT_LODGED` (409).
5. **`ERR_LIVE_REQUEST_EXISTS` hoisted above the band-4 state guard** on waiver-requests and settlement-claims. A presentation holding a live request already sits in `WAIVER_REQUESTED`/`CLAIM_LODGED`, so a strict band ordering makes the declared error unreachable.
6. **Reimbursement commission rate.** §3.9 says 20 bps whenever `available_by != SIGHT_PAYMENT`, but also that the reimbursement leg is "priced as a sight honour". Chose the variant-driven reading: `SIGHT_HONOUR` ⇒ 12 bps even on an `ACCEPTANCE` credit.
7. **Sweep pass 1 vs 2.** §3.8 says the waiver expires "before the preclusion flip" while §3.10 numbers preclusion first. Implemented the literal numbering, with pass 2's `WAIVER_REQUESTED → DISCREPANT` demotion made conditional on the presentation still being `WAIVER_REQUESTED` — both orders then reach identical final state.
8. **Waiver expiry leaves `responded_at` unset** (the scaffold's `PENDING → EXPIRED` side effects omit it, unlike GRANT/DENY).
9. **Pass 5 skips facilities that need no re-derivation**, so a second sweep at the same clock causes no version churn (`recompute_facility` always calls `touch`).
10. **`ERR_DISCREPANCY_CODE_UNKNOWN`** is a membership test against the fixed 10-code UCP list after plain-string shape validation; otherwise the declared error is unreachable. It also covers a waiver citing a non-`MINOR` or non-`IDENTIFIED` code.
11. **`claim_note`, facility-status `reason`** are accepted and validated but not persisted — neither entity declares such a field.

## Step 5: Generate unit tests — 2026-09-03T23:22:00.000Z

The suite is complete. Final state of `/home/ubuntu/github/CodingPRD/tasks/task_2604_trade_finance_letter_of_credit_issuance/`:

## Output

**`test_helpers/`** — 9 files, 2,732 lines (`__init__.py`, `api_client.py`, `api_errors.py`, `assertions.py`, `constants.py`, `factories.py`, `fixtures.py`, `test_users.py`, `types.py`).

**`test_suite/`** — `conftest.py` + **19 test files** (`test_01` … `test_19`), 8,438 lines, **184 test functions**. Every file compiles (`python3 -m py_compile` clean) and every tail ends at a complete statement.

Written this session: `test_18_concurrency_selector_and_sweep_checkpoints.py` (484 lines, 8 tests — the 4 `cross_cutting_complexity_layers` instances: both OCC rules, the confirming-bank selector plus empty pool, the sweep checkpoint) and `test_19_immediate_consistency.py` (238 lines, 4 tests — both `consistency_model` instances).

## Design-index coverage

- **Queue A (Difficulty §1.8):** 18 of 18 instances, 52 tests, >=2 tests each.
- **Queue B (Corner §1.9):** 70 of 73 non-stub instances, 132 tests — entities 12/13, state_machines 11/11, calculations 14/14, validations 7/9, endpoints 7/7, errors 6/6, rbac 7/7, cross_cutting 4/4, consistency_model 2/2.
- 13 corner stubs (`excluded_because`) emitted nothing; verified programmatically that no stub name is tagged.
- Verifier on the whole suite: `files=19 tests=184 tagged_instances=88 / no problems` — every test carries exactly one resolvable `Design:` line, every docstring carries a verbatim >=40-char PRD span, no unused imports.

## Skipped instances (3, all non-unique-derivability; none PRD-silent)

1. `Corner/entities/bank_system_and_computed_fields_input_ignored` — design demands 422 `ERR_INVALID_REQUEST` for a `POST /banks` body carrying `eligibility_score: 9999`, but §2.4's only rule on unrecognised input ("an `id` present in a request body is ignored") mandates the opposite disposition.
2. `Corner/validations/applicant_kyc_pending_blocks_credit_approval` — §3.2 refuses the *draft* for a `PENDING` applicant and no endpoint can later clear `kyc_status`, so the approve-time trigger is unreachable.
3. `Corner/validations/temporal_validation_expired_facility_cannot_carry_a_new_issuance` — every reachable variant co-fires `ERR_SHIPMENT_AFTER_EXPIRY`, which outranks `ERR_FACILITY_EXPIRED` under §2.9.

## Design literals corrected against the PRD (translated, not skipped)

New this session: the sweep instance's dry-run assertion `examination_status == UNDER_EXAMINATION` was corrected to `WAIVER_REQUESTED` (a pending waiver moves the parent there, and the instance's own later assertion says pass 1 scans `WAIVER_REQUESTED`); the selector instance's call ordering was split so the ranking half runs with all three banks `ACTIVE` (the design suspended two banks *before* both triggers, which would have made its own "the lower weighted score loses" assertion vacuous); the refusal instance's `refusal_notice_sent_at` was written in §2.4's three-digit millisecond form. Earlier corrections stand as previously reported (dropped `draft_max`/`draft_committed`, the null `net_proceeds_cents` on a refused claim, the unresolvable-principal waiver call, the PRD-contradicted `ERR_DISCREPANCY_CODE_UNKNOWN` raise, the foreign-applicant presentation read, the non-existent `GET /applicants` count, and `document_count` 0 -> 1).

Nothing under `workspace/` was read, created or modified.

**Orchestrator note:** verified `test_helpers/` and `test_suite/` both live at the task root (not under `workspace/`), so Step 7 can run them in place.

## Step 7: Run tests and iterate — 2026-09-04T00:05:00.000Z

All 8 rounds green. Final report.

## Summary

**Iterations run: 2** (sweep 1 → 11 deterministic failures; fix batch; sweep 2 → clean).

### Final sweep (8 parallel rounds, `setsid nohup`, `--isolation per-test-server`)

| round | passed/total | failed | errors |
|---|---|---|---|
| 1 | 184/184 | 0 | 0 |
| 2 | 184/184 | 0 | 0 |
| 3 | 184/184 | 0 | 0 |
| 4 | 184/184 | 0 | 0 |
| 5 | 184/184 | 0 | 0 |
| 6 | 184/184 | 0 | 0 |
| 7 | 184/184 | 0 | 0 |
| 8 | 184/184 | 0 | 0 |

Union of failures across all 8 rounds: **0**. The eight `results/results.$i.json` files are left in place.

### Sweep 1 diagnosis (11 failures, identical in all 8 rounds — zero flakiness, no reaping/load symptoms)

**Tests deleted: 0.** One partial-coverage assertion removed under STEP 1c:
- `test_17_role_and_principal_guards.py` (`test_the_whole_instrument_runs_once_through_all_eight_roles`) — removed `assert posting["amount_cents"] == 1000000`. Category: **COMPUTED-FIELD / RESPONSE-SHAPE SILENCE**. PRD §3.1's collateral paragraph specifies only the request fields (`amount_cents`, `posting_note`, `expected_facility_version`) and the facility-side effects; it never declares a `CollateralPosting` entity, its response fields, a GET, or a listing, so "return the created posting" vs "return the mutated facility" is not uniquely derivable (the suite's own dominant reading, e.g. `test_12` reading `first["version"]`, is the facility). Scaffold rule that drove generation: `Corner/rbac/every_role_can_run_its_own_exclusive_operations_end_to_end`. The PRD-covered assertions in the same test (facility ledger triple, `collateral_posted_cents == 1000000`) were kept.

**Fixes to `test_helpers/` (1 file, 5 tests):**
- `test_helpers/fixtures.py::draft_credit` — the helper passed the four party ids positionally to `f.credit_payload(...)` and then splatted `**overrides`, so any test drafting on a *second* facility of the same applicant died with `TypeError: credit_payload() got multiple values for argument 'facility_id'`. Now the four ids are `overrides.pop(...)`-ed with the `parties` values as defaults and passed as keywords. This was the ">=5 tests share one setup error" triage case: it fixed `test_06_boundary_precision.py`, `test_07_cross_entity_state_gates.py` and `test_10_entity_contracts.py` failures at once.

**Fixes to `test_suite/` (2 faithfulness corrections, no weakening):**
- `test_08_window_occupancy_and_cooling_off.py::_rejected_round_then_a_draft` — the helper asserted `consent_window_start == "2026-08-10"` against the **DRAFT** snapshot and discarded `issue_amendment()`'s return. PRD §3.5: a draft's window is unset and issuance is what sets `consent_window_start` to the clock date. The helper now returns the issued row.
- `test_11_lifecycle_state_machines.py` (manual-suspension test) — expected `ERR_FACILITY_NOT_ACTIVE` on issuing a credit the suspension cascade had already moved to `ON_HOLD`. PRD §2.9 band 4 evaluates the addressed row's own transition first ("the addressed row is in a state from which the requested transition exists, else the specific 409 for that instrument (`ERR_CREDIT_NOT_DRAFT`, `ERR_CREDIT_NOT_APPROVED`, …); cross-entity state guards hold"), so §3.3's `ERR_CREDIT_NOT_APPROVED` is the PRD-determined answer. The sibling test at the `FROZEN`-posture site still asserts `ERR_FACILITY_NOT_ACTIVE` and still passes, because that credit is genuinely `APPROVED`.

**Fixes to `implementation/` (1, 3 tests):**
- `workspace/implementation/ledger.py::rebase_allocation` — it overwrote `credit["total_charge_cents"]` with `retained_charges + amendment_fee` and derived `chargeable_utilisation_cents` from that. PRD §3.5 verbatim lists `total_charge_cents` among the fields "**not** re-priced" by an amendment and states the credit's `chargeable_utilisation_cents` "remains `committed_allocation_cents` plus `total_charge_cents` under the pinned charge order and therefore excludes amendment fees altogether." The overwrite is gone and `chargeable_utilisation_cents` now derives from the pinned issuance total; the allocation row's `charge_cents` still carries `retained + fee`, preserving the PRD's deliberate asymmetry on the facility ledger.

### Notes
- The start command is `bash workspace/implementation/start.sh` (not `workspace/start.sh`); a first relaunch attempt with the wrong path exited all 8 rounds instantly with `ServerStartError ... code 127` and no results files. Worth remembering for future sweeps of this task.
- Latent, not implicated by any observed failure: `test_helpers/factories.bank_payload` builds `swift_bic` as `f"TSTBK{n:03d}"` from a module-level counter; once that counter passes 999 the BIC becomes 9 characters and would violate the PRD's 8-or-11 rule. Left untouched since no round comes close to 1000 banks.
- No entity data is seeded or persisted in `implementation/` (storage is process-local dicts in `db.py`); no assertion was downgraded, skipped or xfailed; no endpoint, field, side effect or header was added.

### Orchestrator independent verification (not the subagent's claim)

The subagent wrote its final sweep to `results/results.$i.json` rather than the documented `workspace/implementation/` location, so the orchestrator re-ran the whole 8-round sweep itself under `setsid nohup`, writing to `workspace/implementation/results.{1..8}.json`. Result: **8/8 rounds at 184/184, failed 0** (independent confirmation of the clean sweep). The subagent's misplaced `results/` directory was then removed and its clean artifacts superseded by the orchestrator's own. Also verified directly: 184 test functions still present (none lost), **0** occurrences of `pytest.mark.skip` / `pytest.mark.xfail` anywhere in `test_suite/` or `test_helpers/`, and no `sqlite` / `json.dump` / `/tmp` persistence anywhere in `implementation/`.

## Step 8: Finalize PRD — 2026-09-04T00:12:00.000Z

Done. `PRD_FINALIZED.md` written with two edits.

## Line counts
- `PRD.md`: 515 lines / 119,200 bytes
- `PRD_FINALIZED.md`: 515 lines / 119,990 bytes — **0.00% line delta**, +0.66% bytes (both edits are inline inside existing paragraphs; tail still ends at `| ERR_COLLATERAL_RELEASE_BLOCKED | 422 |`)

## Changes
- **§3.1 (Collateral paragraph) — insert** — pinned that a collateral posting creates no `CollateralPosting` record and exposes none through any endpoint, that `posting_note` is accepted but appears in no response, and that a successful call returns the updated `CreditFacility` row itself with HTTP 200 (new `collateral_posted_cents`, incremented `version`, and no `amount_cents` of its own) — `implementation/routes_parties.py:186-206` (`return ok(public(facility))` at :206).
- **§3.3 (issuance preconditions) — revise** — pinned that the credit's own state gate precedes the facility gate, so a credit the suspension cascade already moved `APPROVED → ON_HOLD` is refused `ERR_CREDIT_NOT_APPROVED`, not `ERR_FACILITY_NOT_ACTIVE` — `implementation/routes_credits.py:401-404`.

## Items deliberately NOT patched
- `test_helpers/fixtures.py::draft_credit` (positional/kwarg `TypeError`) and the latent `bank_payload` BIC counter — pure fixture bugs, no PRD implication.
- `test_08` consent-window helper — PRD §3.5 already determines that a draft amendment's `consent_window_start` is unset and that issuance sets it to the clock date; impl matches (`routes_amendments.py:129-131` vs `:200-202`). Prose kept verbatim.
- `ledger.py::rebase_allocation` — the Step 7 fix moved impl *onto* PRD §3.5's verbatim text (`total_charge_cents` not re-priced; `chargeable_utilisation_cents` = `committed_allocation_cents` + `total_charge_cents`; allocation row `charge_cents` = retained + fee). Confirmed at `ledger.py:318-337`. No PRD change.

## Per-edit pre-edit search log

**Edit 1 — §3.1 collateral posting response**
- (a) Subject: the collateral-posting write — whether a posting entity exists, what row the response carries, and the status code.
- (b) Paths enumerated: `routes_parties.py:186-206` (the only route touching `collateral_posted_cents` besides facility creation at `:173`); `grep -rn "collateral" implementation/*.py` → only `calc.py:164-178` (step-4 collateral credit, read-only), `ledger.py:163-177` (`collateral_credited_to_open_allocations`, guard only, creates no row), `errors.py:81`; `db.py:17-32` `ENTITY_COLLECTIONS` (no collateral-posting store) and `db.public()`; `response.py:27-33` (`ok`=200 vs `created`=201); sibling POST sub-collection `routes_parties.py:209-247` (`status-changes`, also 200 + facility) to confirm the wording doesn't clash; §4 table row (`PRD.md:413`) and §2.2/§4 status-code rules.
- (c) Adjustment: dropped a first draft that said the response carries "refreshed exposure figures and posture" — `post_collateral` calls only `touch(facility)`, never `recompute_facility`, so that would have implied a recomputation the impl does not perform. Re-scoped to "the facility's own fields, among them the new `collateral_posted_cents` and the incremented `version`". Also left the `posting_note` length bound (impl: <=500 chars) untouched as out of scope.

**Edit 2 — §3.3 own-state vs facility gate at issuance**
- (a) Subject: relative order of the addressed credit's state check and the cross-entity facility state guard on `POST /credits/{id}/issue`.
- (b) Paths enumerated: `routes_credits.py:393-431` (full issuance gate chain: credit state → facility → screening → advising bank → facility expiry → fiscal); `guard_credit_state` at `routes_credits.py:75-82` (terminal statuses short-circuit to `ERR_CREDIT_TERMINAL`); `approve_credit` at `:374-386` (same own-state-before-facility ordering); `routes_parties.py:217-224` (`SUSPEND` → `hold_approved_siblings`) and `:235-244` (`CLOSE` does **not** cascade, which is why the `FROZEN` sibling test still legitimately sees `ERR_FACILITY_NOT_ACTIVE`); `ledger.py:92-107` cascade hops; `routes_amendments.py` issue/consent ordering; §2.9 band 4 and the §2.9 "two consequences" paragraph.
- (c) Adjustment: rejected a broader draft asserting "the six preconditions are gated in the order listed" — impl evaluates screening (band 5) *before* `ERR_ADVISING_BANK_INELIGIBLE` and `ERR_FACILITY_EXPIRED`, so that universal claim would have been false. Narrowed to the credit-state/facility-state pair only. Also dropped a contrast clause about a still-`APPROVED` credit on a suspended/closed/`FROZEN` facility (redundant with the precondition itself, and `FROZEN` only ever coexists with `CLOSED` per `ledger._set_posture`), and named only the `ON_HOLD` case so the sentence stays true when the credit is terminal (`ERR_CREDIT_TERMINAL`).

**Orchestrator verification:** `PRD_FINALIZED.md` is 515 lines / 119,990 bytes, tail ends at `| ERR_COLLATERAL_RELEASE_BLOCKED | 422 |` (real section boundary), and a folded diff against `PRD.md` shows 42 changed 80-col lines — a genuinely localized patch, not a rewrite.

## Step 9: Complete PRD — 2026-09-04T01:00:00.000Z

Run as **three sequential file-partitioned passes** over `implementation/` rather than one agent, because a single Step 9 subagent reliably under-scans a 4,174-line implementation (and in the worst case leaves `PRD_COMPLETED.md` byte-identical to its source, proving the scan never happened). Pass 1 owned Step 0's `cp`; passes 2 and 3 edited the same file in place.

### Pass 1 — `app.py`, `response.py`, `errors.py`, `middleware.py`, `db.py`, `validate.py`, `routes_parties.py`, `routes_credits.py`
**53 changes: 44 ambiguity-pins, 9 mismatch-revisions.** Highlights of the mismatches: `api_request_timestamp` is the one field read from the host wall clock, not the logical clock (`response.py:23`), so §2.5's "nothing reads the host wall clock" was narrowed; `version`/`updated_at` bump once per row per request (first touch only) rather than on every mutation, so a multi-write cascade still ends one version higher (`db.py:148`); the `REINSTATE` gate is a pure exposure test regardless of `suspended_reason` (`routes_parties.py:210`); `ERR_ADVISING_BANK_INELIGIBLE` fires only on `status != ACTIVE` because a flagged bank is caught by `ERR_SANCTIONS_BLOCK` first (`routes_credits.py:230-236`); no path compares `expiry_date` to the clock or `issue_date` at drafting, so a past-expiry credit issues on the one-quarter floor (`routes_credits.py:253-255`); CONFIRM re-forms `total_charge_cents` from a freshly derived base commission while leaving stored `base_commission_cents` alone, so the three can diverge after an amendment, and it **sets** rather than raises the OPEN allocation's `charge_cents` (`routes_credits.py:564-585`); `declined_reason` is validated then discarded and the decline exclusion binds only the selector (`routes_credits.py:554-562`). Ambiguity pins covered header trimming, per-role read scoping, the `req_` + 20-char id shape, pre-routing/parse failures, pagination and filter semantics, `created_at` tie-break by insertion order, band-2/3/5 internal ordering, and global free-text caps.

### Pass 2 — `routes_amendments.py`, `routes_presentations.py`
**38 changes: 22 ambiguity-pins, 16 mismatch-revisions** (§3.5 = 14, §3.6 = 10, §3.7 = 9, §3.8 = 5). Highlights: the amendment fee's quarter count is measured to the **amended** `expiry_date`, not the credit's stored one (`routes_amendments.py:191-196`); the consent-free `ACCEPTED` edge applies **no** fiscal test at all, so it can drive the facility over its limit (`:212-217`); the incoterm/insurance pairing is re-checked only when `change_set` carries an `incoterm` key and runs *after* the window-overlap test (`:74-80,185`); submission applies no credit-state guard — the presentation window is the only door that closes (`routes_presentations.py:315-320`); `maturity_date` is `received_date` + `tenor_days` gated on `tenor_days == 0` alone, not on `available_by` (`:365`); a `BLOCKED` submission still persists its screening row and cascades the beneficiary before returning 403 (`:328-333`); the ten-code discrepancy list is the whole test, the credit's documentary requirements never consulted (`:465-466`); `ERR_LIVE_REQUEST_EXISTS` is evaluated ahead of the waiver state guard (`:522-530`); `request_waiver` applies no examination-deadline gate (`:512-556`); the refusing examiner is not recorded (`:605-640`); screening `PENDING` is a declared status no persisted row is ever observed at (`:103-121`); a `BLOCK` review writes to no presentation or claim — the freeze is realised entirely by the settlement gate reading the newest check (`:410-434`).

### Pass 3 — `routes_settlement.py`, `routes_ops.py`, `calc.py`, `ledger.py`
**21 changes: 13 ambiguity-pins, 8 mismatch-revisions.** Highlights: dropped the false "`available_cents` may never go negative" — the consent-free amendment branch is ungated and the raw subtraction is stored (`ledger.py:123`); the sweep runs the presentation pass before waiver expiry, so a `WAIVER_REQUESTED` file is already `PRECLUDED` when the waiver expires and the `DISCREPANT` demotion is skipped (`routes_ops.py:198-204`); `variant_applied` is populated at lodging and derives from `claim_type` alone, not `available_by`, and `REJECTED` is never produced (`routes_settlement.py:115`, `calc.py:270`); commission rate is keyed on the variant, so a `REIMBURSEMENT` on a usance credit prices at 12 bps (`calc.py:283-287`); `days_to_maturity` is signed, so a past maturity yields a negative unfloored `discount_cents` and falsifies "sight honour always yields a strictly larger net" (`calc.py:306-310`); the presentation moves by `claim_type` (`REIMBURSEMENT` → `REIMBURSED`, not `PAID`) (`routes_settlement.py:169-189`); `UTILISED` tests `available_cents == 0` alone, not the stated reserved/drawn equivalence (`ledger.py:225-235`). All five sweep passes, every counter definition, `dry_run`'s snapshot-and-restore, and the two cross-pass ordering dependencies are now pinned. Pass 3's closing statement: no known gap remains in its partition; the only unpinned `calc.py`/`ledger.py` branches are defensive fallbacks on states the API cannot reach, deliberately left unwritten rather than inventing behaviour.

### Totals and orchestrator verification
**112 changes across the three passes: 79 ambiguity-pins, 33 mismatch-revisions.**

`PRD_COMPLETED.md` is **518 lines / 151,501 bytes** (source `PRD_FINALIZED.md`: 515 / 119,990) — +3 lines, **+26.3% bytes**, 1,240 changed 80-column lines. Independently verified by the orchestrator: the file is **not** byte-identical to `PRD_FINALIZED.md` (the tell that the scan never ran), its tail still ends at `| ERR_COLLATERAL_RELEASE_BLOCKED | 422 |`, and the heading count is unchanged from `PRD.md`, so no new sections were added — the three passes only inserted and revised inline as instructed.

Steps 8 and 9 edited documentation only; no file under `implementation/` was modified after the clean sweep (latest implementation mtime 23:37, the verification sweep ran 23:56–00:05), so `workspace/implementation/results.{1..8}.json` at 184/184 remain valid for the delivered code.

**PIPELINE COMPLETE.**
