# Worklog — task_2228_livestock_mandatory_price_reporting

## Step 1: Create task directory — 2026-09-01T00:00:00.000Z

Created `tasks/task_2228_livestock_mandatory_price_reporting/` and `tasks/task_2228_livestock_mandatory_price_reporting/workspace/` (allocated name used verbatim; no index scan performed).

## Step 2: Generate scaffold — 2026-09-01T09:33:00.000Z

All three scaffold artifacts for `task_2228_livestock_mandatory_price_reporting` are complete and lint-clean.

**Files:**
- `SCAFFOLD.yaml` (2769 lines) — §1.0–§1.7 only, no design keys
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (3163 lines) — single key `scaffold_difficulty_design`
- `SCAFFOLD_CORNER_DESIGN.yaml` (4262 lines) — single key `scaffold_corner_design`

**Scaffold surface (§1.1–§1.7):** 12 entities, 7 state machines (Registration, ReportingWindow, Submission, MarketReport ×3 parallel dimensions, AuditCase, PenaltyAssessment, MethodologyChange), 2 OCC concurrency rules, 11 calculations, 53 ordered validations, 55 endpoints, 60 error ids, 6 roles. Profile: `difficulty_level: expert_plus`, layers `rate_threshold_triggers / optimistic_concurrency / cascading_side_effects / dual_variant_calculation`, `role_model: segregation_of_duties`, `consistency_model: immediate`.

**§1.8 depth probe:** 9 hard-reasoning rules × 25 instances (dual-variant, combinatorial formula, non-linear state machine, transitive cascade, priority-pair conflict, boundary precision, cross-entity state dependency, resource/temporal overlap, compensating invariant).

**§1.9 breadth probe:** all nine claim-extraction-guide sections — entities 10, state_machines 15, calculations 13, validations 20, endpoints 5, errors 2, rbac 5, cross_cutting_complexity_layers 8, consistency_model 2 = **80 instances (52 with full test recipes, 28 `excluded_because` stubs)**. Every stub cites an existing §1.8 instance name; no name collides across the two files; every `${var}` is captured before use; all 60 error ids are triggered by at least one instance across the two designs.

**Design adjudications made in this final pass:**
- `packer_owned_only_filing` — PACKER_OWNED is in the volume set but not the priced set, so the empty-priced-set path yields null price statistics and the suppression cascade stops at its *first* rung (`NO_ELIGIBLE_DATA`) even under relaxed guidelines; publish then fails with `ERR_CONFIDENTIALITY_SUPPRESSION_REQUIRED` at the exact release instant.
- Boxed-beef lots deliberately made non-proportional (10 loads/400 000 lb vs 15 loads/500 000 lb) so head-weighted 288.20 and weight-weighted 288.00 diverge — otherwise the wholesale dual-variant corner would have been vacuous.
- `ERR_CORRECTION_WINDOW_CLOSED` (24) vs `ERR_RESUBMISSION_LIMIT_REACHED` (41): both apply to `open-correction`, so the corner walks the count ceiling first and then the deadline, asserting 24 wins when both are violated.
- Penalty corners split by governing-registration status: `DETERMINED`-only firms give the neutral `volume_factor 1.000` (money gates: 1 000 000 exact), `ACTIVE` firms give 1.126 (563 000 for INACCURATE_DATA, 422 250 for a 3-day-late filing) — this isolates constants from uplift.
- Corrected one literal while writing: the second NON_REGISTRATION assessment records `delinquency_tier_at_assessment == TIER_0` (8 pre-existing points is below the TIER_1 floor of 10), since each assessment reads the tier before its own points.
- `errors` section adds a full ladder-peel instance on `POST /submissions` (401→403→400→plant 404→window 404→foreign 403→412→201) — the only construct that proves rung *order* rather than existence, and it covers `ERR_FOREIGN_REPORTING_ENTITY` / `ERR_STALE_WINDOW_VERSION` in situ.
- Rows with no counterpart in this scaffold (bulk_operations, soft_delete, idempotency, scheduled_actions, multi_tenancy, conditional_feature_flags, derived_field_reconciliation) are skipped with an in-file note rather than faked; no §1.5 endpoint had to be added or weakened, and no `/_<name>` test endpoint beyond the pre-existing `POST /_clock/set_current_utc` was needed.

**Final lint verdict** (clean on first run):

```
Coverage
  §1.5 endpoints declared:    55
  §1.1 entities declared:     12
  §1.8 instances scanned:     25
  §1.9 instances scanned:     52
  Calls scanned (§1.8+§1.9):  1270

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

No sibling task directory was read at any point.

## Step 3: Copy shared files — 2026-09-01T09:33:30.000Z

Copied `INSTRUCTION.md` → `tasks/task_2228_livestock_mandatory_price_reporting/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-01T09:57:00.000Z

PRD generated at `workspace/PRD.md` — 438 lines.

**Structure**

- **§1 Introduction** — 3 paragraphs (system role, the three design tensions, the logical-clock decision).
- **§2 Global Specifications** — 11 subsections: 2.1 RBAC, 2.2 API Response Structure (byte-verbatim from `section-2.2-response-structure.md`, verified), 2.3 Pagination, 2.4 The Program's Logical Clock, 2.5 Common Resource Properties and Immutable Line Items, 2.6 Optimistic Concurrency on Ledger-Bearing Parents, 2.7 Precision: Two Deliberately Opposite Rounding Orders, 2.8 Path and Foreign-Key Resolution, 2.9 The Order of Rejection, 2.10 Cascade Discipline and Re-Aggregation, 2.11 Ledger Conservation and Full Recomputation.
- **§3 Business Logic** — 9 subsections organized as a chronological program lifecycle: firm/plant enrollment → threshold determination, appeal, activation → trade windows → building a filing (purchase types, required/forbidden data elements, forward-commitment peak) → filing/review/correction/supersession → aggregation, publication guidelines, release → audit verification → penalties and settlement → methodology rulemaking.
- **§4** 55-row endpoint table (4 columns), **§5** 60-row error table (2 columns). File ends at §5, no audit footer.

**Hard contract reports**

```
Field coverage check:
- entities[].fields: 120 required, 120 present, 0 missing
- endpoints[].request_body: 65 required, 65 present, 0 missing
- endpoints[].query_params: 27 required, 27 present, 0 missing
- concurrency_rules[].occ_field: 2 required, 2 present, 0 missing
Status: PASS   (verified against exact standalone backticked tokens, not substring matches)
```

```
Rule coverage check:
- validations[] with priority: 52 checked, 52 expressed in prose, 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write_endpoint + expected_<parent>_version + error_id + 412 all named), 0 missing
- state_machines[].transitions: 41 checked, 41 fully expressed, 0 missing
- calculations[]: 10 checked, 10 fully expressed, 0 missing
- validations[] conditions: 52 checked, 52 matchable to error_id in prose (all 60 error IDs appear), 0 missing
- endpoints[].side_effects / applies_to: 55 endpoints checked, all expressed, 0 missing
- entities[].fields[] structured content: 120 checked, 120 reconstructible from prose, 0 missing
- sibling-branch symmetry: 8 groups checked (accept/reject from SUBMITTED vs RESUBMITTED, RECONCILED vs DISCREPANCY, PENDING→COMPUTED vs STALE→COMPUTED, CLEARED vs WITHHELD, admin vs delinquency suspension, DRAFT vs SUBMITTED voiding, RECONCILED→CLOSED vs DISCREPANCY→CLOSED, FIVE_YEAR_AVERAGE vs PRIOR_YEAR_ACTUAL), 8 with equal prose density, 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 873
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

**Scaffold conflicts resolved (2-of-3 sourcing, noted for the record)**

1. `registration_number` minting — field description + state machine say *activation*; the `determine` endpoint's `side_effects` said it too. Wrote it as minted on activation only.
2. `resubmission_count` increment — state machine (resubmit) + field description ("completed correction rounds") vs `open-correction` endpoint `side_effects`. Wrote it on the resubmit transition; either reading yields the same ceiling-of-2 behavior.
3. `industry_notice_issued_at` — field description + state machine say *adoption*; `close-comment` endpoint `side_effects` also claimed it. Wrote it on adoption only.
4. Slaughter-history completeness — the calculation checks all five lookback years unconditionally, while validation priority 43 makes it basis-dependent. Followed validation 43 (five years for `FIVE_YEAR_AVERAGE`, one year for `PRIOR_YEAR_ACTUAL`), since the validation table is what drives rejections.
5. `Plant.species` must equal the owning firm's `species_scope` — this constraint has no error code assigned anywhere in the scaffold (`ERR_SPECIES_CLASS_MISMATCH` is scoped only to submission and market-report creation), so it is stated as an invariant without nominating a code, rather than inventing one.

## Step 5: Generate unit tests — 2026-09-01T11:35:00.000Z

Test suite for task 2228 (Livestock Mandatory Price Reporting) is complete, audit-clean, and green against the reference implementation.

## Result

`107/107 passed` (80s, run with `--isolation per-test-server`), coverage audit clean: 25/25 difficulty instances (>=2 tests each), 52/52 non-stub corner instances, no untagged/dual-tagged tests, every `PRD §X.Y` citation verbatim and >=8 words, no scaffold references. `pyflakes` silent, `compileall` clean. Zero instances skipped.

## Files

Helpers — `test_helpers/`: `types.py`, `api_client.py`, `api_errors.py`, `constants.py`, `test_users.py`, `factories.py`, `assertions.py`, `fixtures.py`, `__init__.py`.

Tests — `test_suite/`: `conftest.py` plus `test_01` … `test_16`. Queue A (difficulty) = `test_01`–`test_09`, 55 tests. Queue B (corner) = `test_10`–`test_16`, 52 tests.

## Defects found and fixed during execution triage

- Invalid deadline triple in the shared window literals: `WINDOW_PUBLICATION_RELEASE` predated `WINDOW_CORRECTION_DEADLINE`, violating PRD §2.9 ("`submission_deadline_utc` must be no later than `correction_deadline_utc`, which in turn must be no later than `publication_release_utc`"). Fixed in `test_helpers/constants.py` and the four window dicts in `test_suite/test_08_temporal_overlap.py`.
- `TypeError: reporting_window_payload() got multiple values for keyword argument 'min_reported_head'` — `relaxed_guideline_window_payload` and `create_standard_window` passed their defaults positionally alongside `**overrides`. Both now merge into a dict first.
- Clock-written stamps (`published_at`, `submitted_at`, `accepted_at`, `computed_at`, `received_at`, `effective_from`, `industry_notice_issued_at`) were compared by string to the clock literal; the implementation serializes them with three fractional digits. The PRD fixes the instant, not the digit count, so I added `assertions.assert_clock_stamp()` (instant comparison plus an ISO-8601 shape check) and routed all 13 sites through it.
- `test_03_state_machine_paths::test_03`: asserted `resubmission_count == 1` at reopening. PRD §3.5 increments it on *refiling*, so the assertion moved to the `RESUBMITTED` record and reopening now pins 0.
- `test_09_compensating_invariants::test_05`: asserted the third assessment recorded `TIER_2`. The tier is read *before* the row's own points (16 at that moment), so `TIER_1` is the derived value; the firm still ends in `TIER_2` and is reinstated by the waiver.
- `test_13_validation_rejections::test_06`: asserted `measured_head`/`threshold_head` are null on a `DRAFT` file. PRD §3.2 only states `determination_outcome` "remains null for as long as the record sits in `DRAFT`", so null-vs-zero is not derivable; the test now pins that a failed determination leaves the record's own creation values, version and outcome unchanged.

## PRD-first divergences from the design indices (design weakened/wrong, PRD followed)

- `boxed_beef_wholesale_aggregation_distinct_from_live_categories`: design wanted `reported_value_dollars == 0.00` on a lots-only filing; PRD §3.5 sums lot values → 2592000.00.
- `zero_verified_denominator_audit_edge_cases`: follow-on — wholesale case finalized at `verified_value_dollars == 1142000.00` to keep the IMMATERIAL/RECONCILED branch reachable.
- `purchase_type_data_element_rules_rejected`: design treated `start == end` as invalid; PRD §3.4 says "no later than", so the probe uses an inverted span.
- `class_and_wholesale_authorization_mismatches_rejected`: design expected `ERR_WHOLESALE_NOT_AUTHORIZED` at submission create; PRD guards the wholesale-lot append.
- `threshold_head_exactly_at_species_floor`: design expected `registration_number` right after determine; PRD mints it on activation.
- `client_supplied_system_fields_are_ignored_extra_field_discarded`: design expected bare-second `created_at`/`updated_at`; PRD §2.5 mandates three fractional digits.
- `derived_counters_are_current_in_the_mutating_response`: design expected `resubmission_count == 1` in the open-correction response; PRD §3.5 increments on refiling → 0.

## Step 6: Generate implementation — 2026-09-01T11:35:30.000Z

Implementation complete and verified. All files live under `workspace/implementation/`.

## Files created (21)

Launcher / config
- `start.sh` (guarded `pip install`, `exec python3 app.py`, honours `PORT`, default 10000, binds 0.0.0.0), `requirements.txt` (`flask>=3.0`)
- `app.py` — app factory, `Decimal`→JSON-number provider with `sort_keys=False`, `before_request` authentication, `ApiError`/`HTTPException`/`Exception` handlers all returning the §2.2 error envelope, 9 blueprints

Core layer
- `errors.py` (all 62 error ids + `HTTP_STATUS_BY_ERROR` + `ApiError`), `clock.py` (logical clock, default `2026-08-01T00:00:00Z`, 3-fraction-digit ISO), `db.py` (12 empty dicts, `insert`/`touch`/`ordered`, monotonic `_seq`), `response.py`, `middleware.py` (6 roles, `roles()` gate), `numeric.py` (Decimal, ROUND_HALF_UP), `validators.py` (shape band 2 + pagination), `serializers.py` (per-entity field tuples), `constants.py`, `lookup.py` (per-entity 404s)

Services
- `services/cascades.py` — submission booked totals (round-then-sum), window ledger + firm penalty ledger full recomputation, staleness/withdrawal chain, `void_in_flight_submissions`
- `services/calculations.py` — threshold determination, lateness, forward-commitment peak, market aggregation (sum-then-round-once), confidentiality guidelines, audit discrepancy, penalty multiplier chain

Routes (55 rules registered, matching the §4 table)
- `entities.py` 7, `registrations.py` 8, `windows.py` 4, `submissions.py` 10, `market_reports.py` 6, `audits.py` 6, `penalties.py` 5, `methodology.py` 7, `clock_routes.py` 1, plus `routes/__init__.py`

## Verification

- Fresh boot via `PORT=… bash start.sh` twice: HTTP up in <3 s, `GET /reporting-entities`, `/submissions`, `/market-reports` all return `total_count: 0` — no seeding anywhere.
- Three end-to-end smoke suites pass with 0 failures, covering: enrolment/duplicate plant code, both determination bases (`measured_head` 140000 pooled-then-floored vs 130010 prior-year), number minting `MPR-2026-0001`, window overlap vs adjacency, stale window version (412), all purchase-type element rules, forward-cap rejection, lateness 1441 min → `days_late` 2, review/accept ledger (2 filings / 350 head), weight-weighted average 176.95, `max_reporter_share_pct` 57.14, publish-before-release (409) then publish + window→PUBLISHED, PublicUser scoping, audit segregation (403) → `MATERIAL_HEAD` → filing UNDER_CORRECTION `AUDIT_MATERIAL_HEAD` + report STALE/WITHDRAWN + window back to LOCKED, penalty 285000 cents with `volume_factor` 1.140, cap clamp after rounding (2280000→2000000), TIER_2 crossing → SUSPENDED + VOIDED drafts, next assessment → REVOKED with doubled points and 1.25 surcharge, waiver → points reversed + reinstatement, ledger conservation invariant, boxed-beef stream with `WITHHELD`/`INSUFFICIENT_REPORTERS` masking (reporter_count retained), `ERR_NO_ELIGIBLE_DATA`, pending-submission lock refusal, methodology notice periods, adoption restatement, pagination bounds and auth/authz codes.

## PRD ambiguities resolved (PRD wins over SCAFFOLD)

- `registration_number` minted at **activate** only (SCAFFOLD claimed `determine`); `resubmission_count` incremented at **resubmit** (not open-correction); `industry_notice_issued_at` stamped at **adopt** (not close-comment).
- Slaughter-history completeness enforced **per basis** (5 years for `FIVE_YEAR_AVERAGE`, prior year only for `PRIOR_YEAR_ACTUAL`), and it is checked before the eligible-plant check so a plantless firm fails with `ERR_NO_ELIGIBLE_PLANTS` (vacuous truth, §2.9).
- `determine` ignores any request-body `basis_variant` (PRD: runs under the stored basis); `redetermine` overwrites it and rolls back the stored basis if the re-run raises.
- Adoption skips `WITHDRAWN` reports, so `restated_report_count` can legitimately be 0; each restated report takes exactly one version bump even when it also goes STALE.
- Recompute of an already-`COMPUTED` report is allowed (no error id exists) and always resets disclosure to `UNREVIEWED`.
- PublicUser report list is filtered to `PUBLISHED`; an explicit non-`PUBLISHED` `publication_state` filter, or a single read of a non-published report, returns `ERR_REPORT_NOT_PUBLISHED` (403).
- Undefined-error choices: duplicate `plant_code` and duplicate `change_code` → `ERR_INVALID_REQUEST` (400); plant species ≠ firm `species_scope` → `ERR_SPECIES_CLASS_MISMATCH` (422); missing substantiation reference on `INACCURATE_DATA`/`LATE_FILING` → `ERR_AUDIT_CASE_NOT_DISCREPANT`; re-locking a non-OPEN window → `ERR_WINDOW_NOT_OPEN`; no submission-state gate on opening an audit case (none defined); unmatched route/405 → error envelope preserving the original status.
- Client-supplied datetimes are echoed verbatim (raw string stored alongside a parsed UTC datetime under `_<field>`), while all server stamps use the 3-fraction-digit form.

## Step 7: Run tests and iterate — 2026-09-01T11:42:00.000Z

The 8-round parallel sweep came back completely clean on the first iteration, so no diagnostic protocol steps were triggered.

## Summary

**Iterations run:** 1 (single 8-round parallel sweep; ~144 s wall time per round, all 8 concurrent).

**Result:** all 8 rounds `passed == total == 107`, `failed=0`, `errors=0`, `skipped=0`. Zero flakiness — the union of failing tests across rounds 1..8 is empty, so no test entered STEP 0 of the diagnostic protocol.

**Tests deleted:** none. No test failed in any round, so no PRD-coverage (STEP 1a) or unique-derivability (STEP 1b) adjudication was needed.

**Fixes applied to `test_helpers/`:** none required.

**Fixes applied to `implementation/`:** none required.

**Notes / verification detail:**
- One process note: the raw results schema uses `tests[].status` (values `passed`/`failed`), not `outcome`. A first parse keyed on `outcome`, which is absent and therefore made all 107 tests look like failures in every round despite the top-level counters reading 107/107. Re-parsed against `status` — genuinely 0 non-passing tests in all 8 rounds. Worth knowing if the parent pipeline scrapes these files.
- Storage-integrity spot check passed: `implementation/db.py` documents and implements empty-on-boot in-memory collections; no SQLite, pickle, shelve, `json.dump`, `/tmp` cache, or startup seeding anywhere under `implementation/`. `start.sh` honors `$PORT` from the runner (defaulting to 10000 only when unset), which is why the 8 concurrent rounds did not collide.
- Results artifacts left in place at `workspace/implementation/results.{1..8}.json`.

**Orchestrator independent verification:** re-read all 8 results files directly — every round reports `passed=107 total=107 failed=0 errors=0 skipped=0`.

## Step 8: Finalize PRD — 2026-09-01T11:43:00.000Z

**SKIPPED** per the skill's skip condition. Step 7 exited on its first 8-round sweep with 0 test deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes — zero iterations beyond the baseline — so `PRD.md` already determined every behavior the implementation exhibits at every site Step 7 could have touched. No `PRD_FINALIZED.md` is produced; Step 9 therefore starts from `PRD.md`.

## Step 9: Complete PRD — 2026-09-01T11:53:00.000Z

`PRD_COMPLETED.md` written.

**Source vs output:** `workspace/PRD.md` 437 lines / 88,098 chars → `workspace/PRD_COMPLETED.md` 437 lines / 98,713 chars (**+10,543 chars**, 34 lines revised in place, no new sections or paragraphs).

**Counts:** 38 ambiguity-pins, 3 mismatch-revisions (41 inline edits total).

### Changes

- **§2.1** — insert — ambiguity — no read endpoint is identity-scoped; ownership applies only to the filing-chain writes and the appeal — `routes/submissions.py:522`, `routes/entities.py:65`
- **§2.1** — insert — ambiguity — penalty segregation check fires whenever an `audit_case_id` is named (any violation type) and is skipped when the case has a null `finalized_by_user_id` — `routes/penalties.py:243`
- **§2.1** — revise — **mismatch** — public report *list* silently narrows to `PUBLISHED` rather than rejecting; `ERR_REPORT_NOT_PUBLISHED` only when a `PublicUser` explicitly filters `publication_state` to a non-`PUBLISHED` value — `routes/market_reports.py:226`
- **§2.2** — insert — ambiguity — `api_request_timestamp` is real wall-clock time, not the logical clock — `response.py:16`
- **§2.3** — insert — ambiguity — unparseable `limit`/`offset` is 400; empty-string param counts as omitted — `validators.py:177`
- **§2.3** — insert — ambiguity — `created_at` ties broken by server insertion sequence (total, stable ordering) — `db.py:59`
- **§2.3** — insert — ambiguity — filters are exact string matches, never enum-validated (unknown value ⇒ empty page, not 400); `is_late` accepts `true/1/yes`/`false/0/no` — `validators.py:199`, `routes/entities.py:80`
- **§2.4** — revise — ambiguity — clock response echoes a single `current_utc` field normalised to UTC; backwards moves allowed — `routes/clock_routes.py:192`
- **§2.5** — insert — ambiguity — `created_at`/`updated_at` and all server stamps read the logical clock — `db.py:41`
- **§2.6** — revise — **mismatch** — `ERR_STALE_WINDOW_VERSION` on any inequality, not only when the window advanced past the value — `routes/submissions.py:169`
- **§2.7** — insert — ambiguity — Decimal figures serialise as bare JSON numbers, so trailing zeros are lost — `app.py:30`
- **§2.10** — insert — ambiguity — the `PUBLISHED → LOCKED` fallback only fires on a window currently `PUBLISHED`; masked (nulled) figures survive staleness and return only on recompute — `services/cascades.py:449`, `services/cascades.py:438`
- **§3.1** — insert — ambiguity — `plant_code` 1–200 chars, collision ⇒ `ERR_INVALID_REQUEST`, evaluated *after* the species check — `routes/entities.py:103`, `routes/entities.py:118`
- **§3.1** — insert — ambiguity — plant species disagreement ⇒ `ERR_SPECIES_CLASS_MISMATCH` — `routes/entities.py:112`
- **§3.1** — insert — ambiguity — `boxed_beef_volume_lbs_prior_year` and `forward_commitment_cap_head` default to 0 (so an undeclared cap forbids any `FORWARD_CONTRACT` line) — `routes/entities.py:106`
- **§3.1** — insert — ambiguity — an empty/no-op amendment still bumps `version`; `annual_head_history` replaces wholesale, never merges — `routes/entities.py:144`
- **§3.2** — revise — ambiguity — new determination file carries `measured_head`/`threshold_head` at 0 (not null) and null `suspended_reason` — `routes/registrations.py:271`
- **§3.2** — insert — ambiguity — `appeal_reason` is 1–4000 chars and is validated but not persisted — `routes/registrations.py:305`
- **§3.2** — insert — ambiguity — a failed redetermination rolls the overwritten `basis_variant` back — `routes/registrations.py:338`
- **§3.2** — revise — ambiguity — a `suspended_reason` other than `ADMIN_ACTION` ⇒ `ERR_INVALID_REQUEST` — `routes/registrations.py:388`
- **§3.3** — insert — ambiguity — all five window instants stored/echoed byte-for-byte as supplied — `routes/windows.py:93`
- **§3.3** — insert — ambiguity — locking a non-`OPEN` window ⇒ `ERR_WINDOW_NOT_OPEN`, tested ahead of both other gates — `routes/windows.py:119`
- **§3.4** — insert — ambiguity — new filing starts `lateness_minutes` 0 / `is_late` false / `days_late` 0, `submitted_at`+`accepted_at` null — `routes/submissions.py:221`
- **§3.4** — insert — ambiguity — explicit JSON `null` counts as absent for both required and forbidden element rules — `validators.py:57`, `routes/submissions.py:274`
- **§3.4** — insert — ambiguity — interval check needs both ends supplied and precedes class/element rules; `grid_premium_discount_per_cwt` may be negative or zero — `routes/submissions.py:260`, `routes/submissions.py:252`
- **§3.4** — insert — ambiguity — probe days compared at UTC calendar-date granularity; delivery instants echoed verbatim — `services/calculations.py:111`
- **§3.5** — insert — ambiguity — `review_note` ≤4000 chars, written on every decision so omission stores null and erases a prior note; no ownership check on review — `routes/submissions.py:435`
- **§3.5** — revise — ambiguity — reopening tests the correction deadline *before* the resubmission ceiling — `routes/submissions.py:480`
- **§3.5** — insert — ambiguity — refiling has no correction-deadline gate and retains `correction_reason` — `routes/submissions.py:500`
- **§3.6** — insert — ambiguity — shell initial field values (nulls vs `reporter_count` 0, `source_submission_count` 0, `max_reporter_share_pct` 0.00); no window-status or data precondition on shell creation — `routes/market_reports.py:87`
- **§3.6** — insert — ambiguity — aggregation has no state precondition, is freely repeatable from `COMPUTED`, restores masked figures, and ignores window status — `routes/market_reports.py:103`
- **§3.6** — insert — ambiguity — disclosure review may rerun from `CLEARED`/`WITHHELD`; a rerun over a masked report necessarily yields `NO_ELIGIBLE_DATA` — `routes/market_reports.py:129`
- **§3.7** — insert — ambiguity — an audit case may be opened against a filing in any status; multiple cases per filing allowed; `verified_*`/`finalized_by_user_id` start null — `routes/audits.py:60`
- **§3.7** — insert — ambiguity — the material-finding reopening fires only if the filing is still `ACCEPTED` (otherwise no filing change and no cascade, case still `DISCREPANCY`), and it ignores the resubmission ceiling — `routes/audits.py:120`
- **§3.8** — insert — ambiguity — substantiation rules are requirements not exclusions; a superfluous reference is accepted and stored — `routes/penalties.py:210`
- **§3.8** — insert — ambiguity — `SUSPENDED → REVOKED` is not gated on the tier crossing; no governing registration ⇒ enforcement chain no-ops — `routes/penalties.py:289`
- **§3.8** — insert — ambiguity — `paid_amount_cents` must be a non-negative integer (negative ⇒ 400) and is not persisted — `routes/penalties.py:309`
- **§3.8** — insert — ambiguity — `waiver_reason` required, non-blank, ≤4000 chars — `routes/penalties.py:338`
- **§3.9** — insert — ambiguity — `change_code` 1–200 chars, duplicate ⇒ `ERR_INVALID_REQUEST`, tested before both notice periods — `routes/methodology.py:58`
- **§3.9** — revise — **mismatch** — `restated_report_count` counts every non-`WITHDRAWN` report of the affected category, including those already carrying the proposed variant — `routes/methodology.py:202`

### Notable non-changes

Endpoint set, role lists, error catalogue and HTTP statuses match `errors.py` exactly. The §2.9 precedence bands hold everywhere traced (window-open before supersede before species before duplicate on filing creation; segregation before stale-version; publish's six-gate order; `ERR_NO_ELIGIBLE_DATA` before `ERR_SPECIES_CLASS_MISMATCH` on compute), so those needed no edits.
