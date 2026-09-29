# Worklog — task_2426_federally_qualified_health_center_sliding_fee_section_330_compliance

## Step 1: Create task directory — 2026-09-02T16:03:17.835Z

Created `tasks/task_2426_federally_qualified_health_center_sliding_fee_section_330_compliance/` and `tasks/task_2426_federally_qualified_health_center_sliding_fee_section_330_compliance/workspace/`. Index pre-assigned by the invoking pipeline (2426); no index scan or allocation performed.

## Step 2: Generate scaffold — 2026-09-02T17:33:50.306Z

All three artifacts are complete and the lint is clean.

Lint verdict (verbatim, final run):

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           /home/ubuntu/github/CodingPRD/tasks/task_2426_federally_qualified_health_center_sliding_fee_section_330_compliance/SCAFFOLD.yaml
  Difficulty design:  /home/ubuntu/github/CodingPRD/tasks/task_2426_federally_qualified_health_center_sliding_fee_section_330_compliance/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      /home/ubuntu/github/CodingPRD/tasks/task_2426_federally_qualified_health_center_sliding_fee_section_330_compliance/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    72
  §1.1 entities declared:     16
  §1.8 instances scanned:     24
  §1.9 instances scanned:     74
  Calls scanned (§1.8+§1.9):  1404

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## Files

- `/home/ubuntu/github/CodingPRD/tasks/task_2426_federally_qualified_health_center_sliding_fee_section_330_compliance/SCAFFOLD.yaml` (§1.0–§1.7)
- `.../SCAFFOLD_DIFFICULTY_DESIGN.yaml` (single key `scaffold_difficulty_design`)
- `.../SCAFFOLD_CORNER_DESIGN.yaml` (single key `scaffold_corner_design`)

## SCAFFOLD.yaml

`domain_name: fqhc-sliding-fee-section-330-compliance`, `api_prefix: ""`. Profile: primary `compliance_audit`, secondary `pricing_engine`, entity_topology `flat`, state_machine_shape `cyclic`, role_model `segregation_of_duties`, consistency `immediate`; 7 complexity layers (`rate_threshold_triggers`, `dual_variant_calculation`, `cascading_side_effects`, `optimistic_concurrency`, `version_pinning_on_approval`, `selector_policy`, `ops_run_checkpoint`).

- **16 entities**: HealthCenter, PovertyGuideline (`common_fields: false`), BoardMember, ServiceSite, ServiceDefinition, ScopeChangeRequest, FeeSchedule, DiscountTier, Patient, IncomeVerification, Encounter, InabilityToPayWaiver, UDSReport, QualityMeasureResult, SiteVisitFinding, CorrectiveActionPlan
- **11 state machines** (Encounter carries two parallel dimensions: `pps_claim_status` with a BILLED↔PENDING_ADJUSTMENT cycle, and `wraparound_status`), **2 OCC concurrency rules** (`expected_patient_version` on income-verification create; `expected_health_center_version` on fee-schedule adopt), **12 calculations**, **42 ordered validations** (p1 auth → p42 payment-exceeds-PPS), **72 endpoints**, **57 errors** (16 typed 404s), **7 roles** (BoardChair is `entity_backed:BoardMember`).
- Calculation core: dual-variant `fpg_percent` (SCHEDULE_YEAR vs INTAKE_YEAR), half-open discount bands, 8-step `patient_charge_cents` with PROVISIONAL/FINAL variants, `pps_encounter_rate_cents` (single-rounded multiplier product + Medicare upper-limit clamp), pinned-order `wraparound_due_cents`, `uds_composite_quality_rate_pct` (round-per-measure then average), closed-above `uds_income_distribution`, 6-clause `governance_posture`, `fee_schedule_review_status`, two compensating invariants, and a 4-step `compliance_sweep_epoch`.

## §1.8 SCAFFOLD_DIFFICULTY_DESIGN.yaml

**9 rules / 24 instances**: `dual_variant_calc` (2), `combinatorial_formula` (4), `non_linear_state_machine` (2), `transitive_cascade` (3, two at depth 5), `priority_pair_validation_conflict` (3), `boundary_precision_check` (3), `cross_entity_state_dependency` (3), `resource_temporal_overlap` (2), `compensating_invariant` (2).

## §1.9 SCAFFOLD_CORNER_DESIGN.yaml

**9 sections / 89 instances = 74 real recipes + 15 `excluded_because` stubs**: entities 12, state_machines 12 (3 stubs), calculations 10 (4 stubs), validations 31 (6 stubs), endpoints 6, errors 3, rbac 5, cross_cutting_complexity_layers 9 (2 stubs), consistency_model 1. Sections/claim_types are taken verbatim from `references/claim-extraction-guide.md`; all 15 stubs cite an existing §1.8 instance by name and carry no `test_recipe`.

## Design adjudications

- **Two shared bootstraps as YAML anchors** (`BOOT_CORE`, `BOOT_PT`) reused across §1.9, with the HealthCenter version trace pinned deterministically (create 1 → site 2 → service 3 → seat 4 → adopt 5, then suspend 6 / reinstate 7 / lock 8); §1.9 has its own anchor set since anchors don't cross files.
- **Chair-before-adopt ordering**: a SEATED BoardMember must exist and a fresh `GET /health-centers/{id}` must immediately precede every `adopt`, otherwise p14 or p10 pre-empts the intended assertion.
- **`compute` on a DRAFT UDSReport is a legal non-transition op**, otherwise DRAFT→SUBMITTED's `computed_at is not null` precondition would be unreachable.
- **Cascading-validation ordering pinned**: with neither a guideline nor an adopted schedule, p36 (`ERR_NO_EFFECTIVE_FEE_SCHEDULE`) must answer, never p37 — because the guideline lookup depends on the selected schedule's `fpg_year`. Reaching p37 in isolation therefore required a two-year schedule `[2026-01-01, 2028-01-01)` covering a 2027 intake date.
- **Error-envelope path**: all asserts use `data.error_id` (per §1.0), never `error.code`.
- Instance names for negative paths use `_rejected` / `_not_found` / `_unauthorized` / `_cannot_` / `_forbidden` suffixes so `scaffold_lint.py`'s `_NEGATIVE_NAME_RE` exempts intentionally-illegal payloads and roles, while endpoint-existence and capture-resolution checks still apply.
- The hard constraint held: no sibling task directory was listed, read, or grepped — the scaffold derives only from the scenario text and the generator skill's own spec.

## Step 3: Copy shared files — 2026-09-02T17:33:50.306Z

Copied `./INSTRUCTION.md` → `tasks/task_2426_federally_qualified_health_center_sliding_fee_section_330_compliance/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-02T17:51:03.340Z

PRD complete.

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_2426_federally_qualified_health_center_sliding_fee_section_330_compliance/workspace/PRD.md` — **581 lines**, ends with the final row of the §5 error table (`| `ERR_PAYMENT_EXCEEDS_PPS_RATE` | 422 |`) plus a trailing newline. No audit footer, no truncation, no mid-table cut.

The two test-targeting index files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were never opened, grepped, or referenced.

**Structure:** §1 Introduction (3 paragraphs) · §2 with 12 domain-specific subsections (RBAC, verbatim response envelope, pagination, common properties + immutable guideline table, logical clock, interval conventions, money/rounding, conserved quantities, award posture and cascade propagation, path resolution, OCC, validation precedence) · §3 with 9 workflow subsections (grantee standup and baseline scope, patient-majority governance, fee schedule and tier ladder, intake and tier assignment, encounter creation and PPS rate, inability-to-pay waiver, billing/wraparound/void, change-in-scope and site visit findings, UDS reporting and the compliance epoch) · §4 endpoint table · §5 error table.

**Hard Contract reports**

- **Contract 1 — Field-Name Coverage: PASS.** Two independent passes (permissive tokenizer, then strict standalone-backtick tokenizer), both with fenced code blocks stripped. 142/142 unique `entities[].fields[].name` present in backticks; 96/96 unique `endpoints[].input` identifiers present (including the 8 non-entity inputs `current_utc`, `decision`, `expected_patient_version`, `expected_health_center_version`, `in_initial_scope`, `receipt_confirmed`, `limit`, `offset`); path param `id` present. Missing: none. Also verified 7/7 role names and 57/57 error ids appear in backticks, and every entity-field enum value (all `enum` members across all 16 entities) appears.
- **Contract 2 — Rule Coverage: PASS.** All 52 transitions across all 11 state machines appear as explicit `FROM → TO` arrow pairs with their preconditions and side effects in prose (two repairs were made during verification: the three encounter void edges were converted from a prose list to explicit `UNBILLED → VOID` / `BILLED → VOID` / `PAID → VOID` / `PENDING_ADJUSTMENT → VOID` pairs; §2.12 rungs 6–7 were amended to point at the enumerated not-found list in §2.10). All 12 calculations are expressed step-by-step in prose with their constants and rounding placement, including both `fpg_percent` variants (SCHEDULE_YEAR vs INTAKE_YEAR), the eight-step `patient_charge_cents` with its single rounding at step four and clamps at five/six/seven, the pinned E1–E6 evaluation order with re-entry at E5, the per-measure-then-average composite (explicitly not pooled), and the S1–S4 sweep order. All 42 validations appear as an ordered ladder in §2.12 in exactly the scaffold's priority order, each paired with its error id, HTTP status, and applies-to scope named by operation; both OCC rules appear in §2.11 with their occ field, guarded operation, and 412 stale-version error.
- **Contract 3 — §3 Path Purity: PASS.** §3 extracted from `## 3.` to `## 4.` (64,662 chars). Zero backticked tokens containing `/`, zero backticked or bare HTTP method names, zero bare URL-path fragments. Endpoints in §3 are referenced only by state-transition pair, role + gerund, or capability description.

**Coverage confirmation:** 16/16 entities, 11/11 state machines (52/52 transitions), 12/12 calculations, 42/42 validations, 72/72 endpoints (verified 72 table rows), 57/57 errors (verified 57 table rows), 7/7 roles. §2.2 is byte-verbatim against `skills/prd-bench-doc-generator/section-2.2-response-structure.md`. No fuzzy quantifiers ("approximately", "roughly", "conservatively") anywhere in the document.

**Orchestrator anti-truncation check:** tail of PRD.md read directly — file ends at the final `## 5. Error Code Catalogue` table row, a real section boundary. Headings present at lines 3/11/216/440/519. Not truncated; no regeneration needed.

## Step 5: Generate unit tests — 2026-09-02T19:15:19.579Z

The suite is complete. Final state:

## Files written

**`test_helpers/` (9 files, Stage 1)** — `__init__.py` (now with an explicit `__all__` re-export surface), `types.py`, `api_errors.py` (57 `ApiErrorId` members, all 16 not-found codes), `constants.py`, `test_users.py` (seven role headers plus `make_board_chair_headers` for the entity-backed chair), `api_client.py` (72 endpoint methods), `factories.py` (30 payload factories), `fixtures.py` (bootstraps `setup_boot_core` / `setup_boot_pt` / `setup_boot_fs` / `setup_boot_gov` plus ~50 scenario builders), `assertions.py`.

**`test_suite/` (conftest + 21 test modules, 120 tests)**
- Queue A (Difficulty, §1.8): `test_01`–`test_09` — **46 tests, 2 per instance, 23 of 24 instances**.
- Queue B (Corner, §1.9): `test_10`–`test_21` — **74 tests, 1 per instance, all 74 non-stub instances** (12 entities, 9 state machines, 6 calculations, 25 validations, 6 endpoints, 3 errors, 5 rbac, 7 cross-cutting layers, 1 consistency model). The 15 `excluded_because:` stubs were not translated.

## Skipped instance (one, gap left as a gap)

`Difficulty/priority_pair_validation_conflict/not_seated_board_member_beats_stale_health_center_version` — the index asserts 403 `ERR_NOT_SEATED_BOARD_MEMBER`, but PRD §2.12 puts the version guard at rung 10 and the seated-seat check at rung 14, so the PRD uniquely derives 412 `ERR_STALE_HEALTH_CENTER_VERSION` instead. No weakened test, no xfail.

## Verification passes (all green)

- `py_compile` + `pyflakes` clean over `test_suite/` and `test_helpers/` (exit 0).
- Design-tag pass: every test has exactly one `Design:` line, it is the last line of the docstring, all 97 distinct tags resolve to real instances, none points at a stub, no test is dual-tagged, no `pytest.mark.skip/xfail`, no "scaffold" mention in generated code.
- PRD-citation pass: all 179 quoted citations verified as whitespace-normalized literal substrings of `workspace/PRD.md`. Three near-misses were fixed (two quotes had a period added where the PRD continues the sentence; one docstring summary had stray quote marks).

## Index-vs-PRD adjudications applied (PRD wins, recorded in the assertions)

`charge_basis` has no `NOMINAL_FEE` member → `SLIDING_FEE_TIER`; `scope_posture` is `CHANGE_FROZEN` not `FROZEN`; `pps_encounter_rate_cents` not `pps_rate_cents`; `PAY_STUBS`, `INSUFFICIENT_DOCUMENTATION`, `HEALTH_PROFESSION` as the real enum members; `submitted_at` / `decided_at` do not exist in the PRD (asserted `submitted_by_user_id` / `decision_note` instead); a refused MCO payment leaves `mco_paid_cents` at 0 and `wraparound_status` `NOT_APPLICABLE`, not null/`PENDING`; and in `pinned_fee_schedule_and_tier_survive_a_later_adoption` the index's version arithmetic omits the grantee bump PRD §3.5 requires on encounter creation, so that test asserts the adoption is *exactly one* grantee mutation relative to a captured pre-value rather than the index's hardcoded 5→6.

## Step 6: Generate implementation — 2026-09-02T19:15:19.579Z

The implementation is complete, boots cold from a fresh process, and all 72 declared endpoints are wired.

## Files written

`/home/ubuntu/github/CodingPRD/tasks/task_2426_federally_qualified_health_center_sliding_fee_section_330_compliance/workspace/implementation/`

- **Entrypoint / infra:** `start.sh` (guarded pip install, then `exec python3 app.py`), `requirements.txt` (`flask==3.1.3`), `app.py` (blueprint registration, error envelope handlers, global request lock, `0.0.0.0:$PORT` default 10000, `static_folder=None`, `strict_slashes=False`)
- **Core:** `db.py` (in-memory dicts, logical clock pinned to `2026-08-01T00:00:00Z` at boot, `_seq` tie-breaker), `errors.py` (58-entry catalog + messages), `middleware.py` (rungs 1–3), `validation.py` (rung 4 strict whitelists, rung 5 pagination, `Decimal`/ROUND_HALF_UP helpers), `response.py`, `serializers.py`
- **Services:** `services/health_center.py`, `fee_schedule.py`, `charge.py`, `cascade.py`, `uds.py`, `sweep.py`
- **Routes (11 modules):** `routes/ops.py`, `health_centers.py`, `guidelines.py`, `board.py`, `sites.py`, `scope.py`, `fees.py`, `patients.py`, `encounters.py`, `uds.py`, `findings.py`, plus `common.py` helpers

## Endpoint count

**72 / 72** — verified programmatically by normalising `app.url_map` against the SCAFFOLD `endpoints:` table: zero missing, zero extra. (2 in the `/_` namespace, 70 domain.)

## Verification performed

Two end-to-end smoke runs against a cold-booted server exercised: grantee/guideline/site/service creation, fee-schedule draft → tier ladder → adopt under OCC, board seating incl. patient-seat qualification (`patient_seat_pct 66.67`, `GOVERNANCE_COMPLIANT`), income verification → VERIFY (`fpg_percent 75.30`, tier assignment), encounter charge (`SLIDING_FEE_TIER`, nominal 2000, PPS 20000), the full ADD_SITE scope cascade (`PROPOSED → IN_SCOPE`), waiver GRANT depth-3 cascade (waived 2000 → wraparound 18000→20000), the NONPAYMENT void block (409), bill → record-payment → claim-wraparound → RECONCILED/RECEIVED coupling, receivable returning to 0, sweep escalation freezing scope, UDS compute (composite 77.8, round-per-measure-then-average), and negative paths (400 pagination, 400 unknown field, 403 role, 404, 409 duplicate/terminal-state, 422 target mismatch). Store confirmed empty on every boot; no sqlite/file/`/tmp` writes anywhere.

## PRD ambiguities resolved

1. **`open_condition_count` conflict** (§2.8 says `status == ESCALATED`, §3.8 says an escalated finding "remains counted while its plan is under consideration") → implemented as `escalated_at is not None and status != RESOLVED`. Submitting a CAP never unfreezes scope; only an *accepted* CAP does.
2. **Derived fields recomputed on read** (counters, postures, `patient_balance_cents`, `sliding_fee_status`, `review_status`) so conserved quantities cannot drift; `version` is incremented explicitly per the endpoint contract.
3. **`created_at` from the logical clock** (required for `cap_due_at = created_at + cap_due_days`), with an internal `_seq` for total ordering on identical instants.
4. **Rung 15 (`ERR_SCOPE_CHANGE_FROZEN`) on `/decide`** enforced on the APPROVE branch only, matching §1.2's per-transition preconditions — it is unreachable on the other branches because a freeze parks SUBMITTED/UNDER_REVIEW into HELD and rung 11 fires first.
5. **`select_schedule_for_patient`** scopes candidates to grantees where the patient has a non-VOID encounter when determinable, otherwise every adopted covering schedule (the PRD's "encounter-independent path" is undefined for a patient with no visits).
6. **DRAFT schedule with `last_reviewed_at == null`** → `review_status` CURRENT unless `fpg_year < latest_guideline_year`.
7. **Tier field errors split by rung:** `discount_pct` outside `(0,1)` is rung 4 `ERR_VALIDATION` (declared constraint); a *missing* `discount_pct` with `PERCENT_DISCOUNT` is rung 31 `ERR_TIER_DISCOUNT_MISMATCH`.
8. **Body owner id vs path id** → `ERR_VALIDATION`, checked *after* the reference resolves so a bad id still 404s (PRD 2.10).
9. **Verify-cascade version bookkeeping:** the patient is bumped once unconditionally (its `sliding_fee_status` is the last recomputation); only grantees owning *affected* encounters are bumped.
10. **Sweep idempotency** at a fixed clock via a pre-mutation `derived()` snapshot; grantee bumps are conditional on an actual change.
11. **SCAFFOLD's stale internal cross-references** ("validations priority 8" for target pairing = actually rung 9; "priority 25" for tier bands = actually rung 32) ignored in favour of PRD §2.12 numbering.
12. **No state gate on adding discount tiers or quality measures** — no ladder rung covers those creates and no catalogued error fits.

## Step 7: Run tests and iterate — 2026-09-02T19:33:55.614Z

Clean sweep on iteration 2. Summary below.

## Iterations run
2 full 8-round parallel sweeps.

- **Sweep 1**: 108/120 in all 8 rounds — 12 deterministic failures, zero flakiness (identical failure set in every round, so nothing load-induced).
- **Sweep 2** (after fixes): **120/120 in all 8 rounds**.

## Tests deleted
**None.** Every failing test's rule was verbatim in PRD.md and uniquely derivable; all 12 were either test-artifact over-specification or a real implementation defect.

## Fixes applied to `test_suite/` (test-side, STEP 2)

The 9 timestamp failures were one class: assertions compared a stamped instant by exact string against the no-fractional-digits rendering (`2026-08-01T00:00:00Z`) while the implementation renders `.000Z`. PRD §2.2 line 95 pins three fractional digits only for `created_at`; for stamped instants §2.3 line 105 says merely "the logical clock's value at the moment of the request", and the clock default is quoted as `2026-08-01T00:00:00Z` — so the *rendering* is not uniquely derivable while the *instant* is. `test_helpers/assertions.py` already ships `same_instant()` with a docstring saying exactly this, and 15 other call sites already use it; these 10 sites had simply not been wrapped. Fix keeps the instant assertion intact and drops only the un-derivable rendering (STEP 1c partial-coverage split):

- `test_suite/test_01_fee_schedule_adoption_and_review.py` — wrapped `last_reviewed_at` at adoption and at annual review; added `same_instant` import.
- `test_suite/test_02_income_verification_tiers.py` — wrapped `expires_at`.
- `test_suite/test_03_encounter_pricing_and_pps_rate.py` — wrapped `in_scope_since` on reinstatement.
- `test_suite/test_06_board_governance.py` — wrapped chair `term_end` and truncated `term_end` on resignation.
- `test_suite/test_08_findings_freeze_and_corrective_action.py` — wrapped `cap_due_at` (2 sites) and `escalated_at`.
- `test_suite/test_09_uds_reporting.py` — wrapped `computed_at`.

Plus one genuine test bug:

- `test_suite/test_14_encounter_validations.py`, helper `_encounter_body` — it forwarded `ctx` ids **positionally** into `create_encounter_payload(patient_id, service_site_id, service_definition_id, **overrides)`, so any test overriding `service_site_id` or `service_definition_id` by keyword raised `TypeError: got multiple values for argument`. Rewritten to build the default payload then `body.update(overrides)`, so overrides win. Fixed `test_an_in_scope_administrative_site_still_carries_no_encounter` and `test_a_service_still_awaiting_admission_cannot_carry_an_encounter` without touching either assertion.

## Fixes applied to `test_helpers/`
None needed — `same_instant` was already present and exported.

## Fixes applied to `implementation/` (STEP 3)

- `workspace/implementation/routes/scope.py`, `decide_request` / `_approve` — the APPROVE branch wrote `req["decision_note"] = note` **before** `_approve()` evaluated the rung-19/20 pre-transition guards, so a decision refused with 409 `ERR_GOVERNANCE_DEFICIENT` still persisted the note onto a request left at `UNDER_REVIEW`. `_approve` now takes `note` and assigns it only after both guards pass, alongside `status = "APPROVED"`. PRD §3.8 line 400 authorizes no mutation on the refused path (only the `REQUEST_REVISION` and `DENY` branches, lines 402/404, are stated to store the note), so the write on an error path traced to no PRD sentence. Fixed `test_a_one_member_board_cannot_approve_a_scope_change`.

No PRD-required check was removed or weakened; no endpoint, field, or side effect was added; no `skip`/`xfail`; no error_id assertion downgraded to a status assertion; storage remains in-memory with no startup seeding.

## Final sweep verification
All 8 files exist on disk at `/home/ubuntu/github/CodingPRD/tasks/task_2426_federally_qualified_health_center_sliding_fee_section_330_compliance/workspace/implementation/results.{1..8}.json`, each parsing with `passed == total == 120`, `failed == 0`, `errors == 0`, `skipped == 0`. Union of failing tests across all 8 rounds is empty. `pyflakes` is clean over `test_suite/`, `test_helpers/`, and `workspace/implementation/`.

**Orchestrator independent verification:** re-listed and re-parsed all 8 `results.N.json` myself (timestamps 19:30–19:31) — 8 files present, each `passed == total == 120`, `failed == 0`, `errors == 0`. Step 7's claim confirmed against disk, not taken on report.

## Step 8: Finalize PRD — 2026-09-02T19:38:50.472Z

Step 8 was NOT skipped: Step 7 ran 2 iterations with 6 `test_suite/` file edits and 1 `implementation/` fix, so the skip condition (zero iterations beyond baseline) did not hold.

Done. `PRD_FINALIZED.md` is written at `/home/ubuntu/github/CodingPRD/tasks/task_2426_federally_qualified_health_center_sliding_fee_section_330_compliance/workspace/PRD_FINALIZED.md`.

## Line counts
- `PRD.md`: 581 lines
- `PRD_FINALIZED.md`: 582 lines (+1 line, **+0.17%**); 3 lines touched total (1 insert, 2 revises).

## Changes
- **§2.2 (API Response Structure)** — *insert* — new bullet pinning that every instant-valued field returned inside `data` renders as ISO 8601 UTC with **exactly three fractional digits** and a trailing `Z` (not just `created_at`): server-stamped instants, the echoed `current_utc`, and client-supplied dates/instants echoed back, with non-UTC offsets and time-less values normalised to UTC, nulls staying null — `implementation/validation.py:59-63` (`iso()`), used at `implementation/serializers.py:12,13,31,32,46,61,62,64,80,124,125,128,129,131,175,176,203,252,287,289,302` and `implementation/routes/ops.py:19`.
- **§3.8 (`APPROVE` preconditions)** — *revise* — appended that a decision refused by any of the three preconditions leaves the request exactly as it stood: still `UNDER_REVIEW`, no `decision_note` stored, no cascade hop fired — `implementation/routes/scope.py:239-248, 175-188`.
- **§3.8 (Approval)** — *revise* — approval also **stores the `decision_note`** (PRD previously named the store only on the `REQUEST_REVISION` and `DENY` branches) — `implementation/routes/scope.py:187`.

No PRD edit for the `test_14` `_encounter_body` fixture bug: it was a pure test-artifact defect (positional/keyword collision), and the two rules it unblocked (`ERR_ADMINISTRATIVE_SITE_NOT_BILLABLE`, `ERR_SERVICE_NOT_IN_SCOPE`) are already verbatim in §2.12 rungs 34/35 and §3.5, matching `implementation/routes/encounters.py:72-82`.

## Per-edit pre-edit search log

**Edit 1 — §2.2 timestamp rendering bullet**
- (a) Subject: the wire rendering of every instant/date-valued field in any response body.
- (b) Paths enumerated: `grep -rn "isoformat\|strftime\|iso("` over the whole implementation → only two renderers exist, `validation.py:iso()` (`%Y-%m-%dT%H:%M:%S.` + 3-digit ms + `Z`) and `response.py:_stamp()` (identical format, wall clock, `api_request_timestamp` only). Read all 21 `iso(...)` callsites in `serializers.py` (every entity incl. `poverty_guideline`, which carries only `id`/`created_at`), plus `routes/ops.py:19` (`current_utc` echo) and `services/sweep.py:77-82` (summary carries no instants; nothing to mis-describe). Confirmed via `grep -rn '"datetime"'` that all 11 client-supplied temporal inputs (`effective_start`, `effective_end`, `board_vote_date`, `target_completion_date`, `term_start`, `term_end`, `resignation_date`, `effective_date`, `encounter_date`, `current_utc`) are parsed by `parse_datetime` (`validation.py:44-56`: `Z`→`+00:00`, naive→UTC, then `astimezone(utc)`), so the normalisation clause is true off the Step 7 site too. Checked `db.py:75-79` (`created_at`/`updated_at` are logical-clock datetimes) and `routes/board.py:131-145` (resignation overwrites `term_end` with the supplied `resignation_date`).
- (c) Adjustment: initially listed "a truncated `term_end`" among clock-stamped instants; `routes/board.py:143` showed it is a copied client-supplied value, not a clock stamp, so `term_end` was moved to the client-supplied group with an explicit parenthetical. Also added the "null stays null" clause so the universal ("every instant-valued field") cannot be read as forcing a timestamp into nullable fields (`in_scope_since`, `adopted_at`, `escalated_at`, `computed_at`, `board_vote_date`, `resignation_date`, `expires_at` are all nullable in `serializers.py`).

**Edit 2 — §3.8 refused-`APPROVE` no-mutation clause**
- (a) Subject: what a refused `APPROVE` decision may write on a `ScopeChangeRequest`.
- (b) Paths enumerated: `routes/scope.py:233-258` (`decide_request` guard order: `state` → `segregation` → `seated_chair` → `_scope_open` → `_approve`) and `routes/scope.py:175-230` (`_approve` raises rungs 19/20 before any assignment). Verified the guards themselves are read-only with respect to the request row: `routes/common.py` `state`/`segregation`/`seated_chair`, `services/health_center.py:governance_posture`, `services/fee_schedule.py:select_schedule_for_health_center`/`review_status`. Also enumerated every other writer of the request row so the clause cannot over-claim: `create_request` (`:82-98`), `submit_request` (`:129-156`), `begin_review` (`:159-172`), and the freeze/unfreeze park cascades at `services/health_center.py:201,217,219`.
- (c) Adjustment: scoped the claim to the request row only ("leaves the request exactly as it stood") rather than "the request is refused with no mutation anywhere" — `_approve`'s pre-guards call `governance_posture`, and elsewhere `hc_svc` recomputation touches the grantee, so a request-scoped claim is the only one true on every path.

**Edit 3 — §3.8 approval stores `decision_note`**
- (a) Subject: the `decision_note` field of `ScopeChangeRequest`.
- (b) Paths enumerated: `grep -rn "decision_note\|held_from_status"` across the implementation → `routes/scope.py:38` (nullable, optional in `DECIDE_FIELDS`), `:95` (initialised null at drafting), `:187` (APPROVE), `:251` (REQUEST_REVISION), `:255` (DENY), `serializers.py:113` (echoed). Confirmed `submit_request` and `begin_review` do **not** clear it (so PRD line 392's "clears `reviewed_by_user_id`" stays complete and my wording must not imply a clear), and the park/unpark cascades at `services/health_center.py:201-219` never touch it. Also checked the same-named but distinct field on `InabilityToPayWaiver` (`routes/encounters.py:297,334,348`) to confirm the §3.6 prose stays correct and my §3.8 edit does not spill onto it.
- (c) Adjustment: reused the existing phrase "stores the `decision_note`" verbatim from the `REQUEST_REVISION`/`DENY` sentences instead of writing something like "records the supplied note when one is given" — all three branches assign `body.get("decision_note")` identically (null when omitted, overwriting any note left by a prior revision round), so the symmetric wording is the one consistent with all three.

**Orchestrator check:** `PRD_FINALIZED.md` exists, 582 lines vs PRD.md's 581, ends at the final §5 error-table row — a real section boundary, not truncated.

## Step 9: Complete PRD — 2026-09-02T19:53:47.563Z

`PRD_COMPLETED.md` is complete at `/home/ubuntu/github/CodingPRD/tasks/task_2426_federally_qualified_health_center_sliding_fee_section_330_compliance/workspace/PRD_COMPLETED.md`.

## Verification
- Final line count: **582 lines** (identical to source — every change is an in-paragraph insert or revision; no new sections, no new paragraphs, no removed content).
- Ends at a real boundary: the last line is the final complete row of the §5 error-code table, `| ERR_PAYMENT_EXCEEDS_PPS_RATE | 422 |`, with a trailing newline.
- Structural parity with the source: 133 table rows, 29 headings, 184 blank lines in both files.

## Counts
- `PRD_FINALIZED.md`: 582 lines / 119,435 chars. `PRD_COMPLETED.md`: 582 lines / 131,262 chars. **Char delta: +11,827.**
- Lines touched: 34. **Ambiguity-pins: 27. Mismatch-revisions: 7.**

## Changes
- §2.4 Pagination — insert — ambiguity — non-integer `limit`/`offset` is `ERR_INVALID_PAGINATION`, an empty-string value takes the default, undeclared filter params are ignored not rejected — `validation.py:203`
- §2.6 Audit fields — insert — ambiguity — derived values are recomputed on every `GET` but a read never advances `updated_at`/`version` — `serializers.py:1`
- §2.8 Conserved quantities — revise — mismatch — `open_condition_count` counts findings with `escalated_at` non-null and `status != RESOLVED`, not `status == ESCALATED` — `services/health_center.py:70`
- §2.9 Owner references — insert — ambiguity — a body-supplied owner id must first resolve (entity 404) and only then agree with the path (400) — `routes/common.py:owner_ref`
- §2.12 rung 4 — insert — ambiguity — strict body whitelist, input-less transition endpoints accept only `{}`, integer/string/`null` handling — `validation.py:124`
- §3.1 Sites — revise — ambiguity — `weekly_service_hours` is an integer, not any number — `routes/sites.py:Field`
- §3.2 Board governance — revise — mismatch — a qualifying encounter's site must also belong to the seat's own grantee — `services/health_center.py:patient_seat_qualified`
- §3.3 Fee schedules — insert — ambiguity — `fpg_year` bounded 2000–2100 and need not be published at drafting; `review_status` is derived, so a fresh draft can read `OUT_OF_DATE` — `routes/fees.py`, `services/fee_schedule.py:review_status`
- §3.3 Discount tiers — insert — ambiguity — `fpg_max_pct` ≥ 0; tier creation has no gate on the schedule's `status` — `routes/fees.py`
- §3.3 Annual review — insert — ambiguity — `reviewed_against_guideline_year` bounded 2000–2100 and unpublished is fine; no state gate; only the schedule's own `version` moves — `routes/fees.py`
- §3.3 `review_status` — revise — ambiguity — an empty guideline table cannot fire the staleness arm; `REVIEW_DUE` requires a non-null `last_reviewed_at` — `services/fee_schedule.py:review_status`
- §3.4 Schedule-year variant — insert — ambiguity — candidate schedules narrowed to grantees with a non-`VOID` encounter for the patient only when that leaves a candidate, then ranked `effective_start`/`created_at` descending — `services/fee_schedule.py:select_schedule_for_patient`
- §3.4 cascade hop 1 — insert — ambiguity — all overlapping `VERIFIED` rows are superseded in ascending `created_at` order and the pointer holds the last one — `services/cascade.py:verify_cascade`
- §3.4 cascade hop 2 — insert — ambiguity — reuses the encounter's pinned `fee_schedule_id`, re-runs only the verification selector, rewrites `sliding_fee_applied` too, and writes a 0 adjustment unconditionally — `services/cascade.py:40`
- §3.4 cascade hop 3 — insert — ambiguity — the patient's `version` always advances, even with nothing recomputed — `routes/patients.py:235`
- §3.4 cascade hop 5 — insert — ambiguity — exactly the grantees owning a recomputed encounter are bumped, once each; none when nothing moved — `routes/patients.py:235`
- §3.4 `sliding_fee_status` — revise — mismatch — falls to `EXPIRED` when *any* verification of the patient is `EXPIRED`, regardless of recency — `services/health_center.py:253`
- §3.5 Verification selector — insert — ambiguity — a supplied `income_verification_id` is checked only for `VERIFIED` + window coverage; its `patient_id` is not matched against the encounter's patient — `routes/encounters.py:64`
- §3.5 charge step one — insert — ambiguity — `income_verification_id` is still pinned for third-party payers — `services/charge.py:29`
- §3.5 Creation side effects — insert — ambiguity — `wraparound_due_cents` is computed at creation, so an MCO encounter is born with a positive residual while `wraparound_status` is `NOT_APPLICABLE` — `routes/encounters.py:132`
- §3.6 Waiver request — revise — mismatch — `waiver_reason` is any non-blank string stored as supplied, not the three-value enum — `routes/encounters.py:275`
- §3.6 GRANT cascade — insert — ambiguity — `CLAIMED → REBILL_REQUIRED` only when the residual actually changed; the waiver, encounter, patient and grantee `version` all bump unconditionally — `routes/encounters.py:355`
- §3.7 Record payment — insert — ambiguity — an MCO encounter with a zero residual keeps `NOT_APPLICABLE` and stops at `PAID`; a non-MCO payer forces residual 0 and `NOT_APPLICABLE` — `routes/encounters.py:205`
- §3.8 Begin review — insert — ambiguity — does not touch the grantee — `routes/scope.py:159`
- §3.8 APPROVE preconditions — insert — ambiguity — the staleness check is vacuous when no adopted schedule covers the clock — `routes/scope.py:182`
- §3.8 Approval hop 1 — insert — ambiguity — the departing-status guard fails silently; the request still becomes `APPROVED` and hops 3–5 find nothing — `routes/scope.py:193`
- §3.8 Compensating cascade hop 1 — revise — mismatch — recount uses the §2.8 definition (`escalated_at` non-null and not `RESOLVED`) — `services/health_center.py:70`
- §3.9 UDS report creation — insert — ambiguity — `reporting_year` accepted only 2000–2100 — `routes/uds.py:39`
- §3.9 Quality measures — insert — ambiguity — attachable in any report `status`, and the report row is left untouched — `routes/uds.py:167`
- §3.9 Income distribution — revise — mismatch — counted-verification cutoff is strictly before 1 Jan of the following year (all of 31 Dec counts) with no lower bound — `services/uds.py:16`
- §3.9 Composite rate — insert — ambiguity — every measure's `updated_at`/`version` advance on each compute, excluded ones included — `services/uds.py:85`
- §3.9 Adjudication — insert — ambiguity — `RETURN` also records `adjudicated_by_user_id` — `routes/uds.py:154`
- §3.9 Compliance sweep — revise — mismatch — S1 writes the patient row and enrols its grantees; S4's set is the touched grantees plus those whose start-of-sweep derived snapshot moved, and `recomputed_health_center_count` is that set's size — `services/sweep.py:26`
- §5 preamble — insert — ambiguity — an unmatched path returns `ERR_VALIDATION` with 404 and a disallowed method with 405, the only two exceptions to its 400; trailing slashes match the same route — `app.py:57`

**Orchestrator check:** `PRD_COMPLETED.md` exists at 582 lines / 131,262 chars, ends at the final §5 error-table row — a real section boundary. Step 9 edited documentation only; `implementation/` was untouched after Step 7, so the verified 8/8 × 120/120 sweep still describes the shipped code. Pipeline complete.
