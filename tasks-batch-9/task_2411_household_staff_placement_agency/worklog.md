# Worklog — task_2411_household_staff_placement_agency

## Step 1: Create task directory — 2026-09-02T10:03:05.550Z

Created `tasks/task_2411_household_staff_placement_agency/` and `tasks/task_2411_household_staff_placement_agency/workspace/` (directory name pre-allocated by the caller; no index scan performed).

## Step 2: Generate scaffold — 2026-09-02T13:47:00.000Z

RESUME NOTE (orchestrator decision, no user available to consult): on entry the filesystem held a complete `SCAFFOLD.yaml` (3798 lines, top-level keys §1.0–§1.7 verified: scenario, domain_name, api_prefix, complexity_profile, response_envelope, global_constants, entities, state_machines, concurrency_rules, calculations, validations, endpoints, errors, roles — tail intact, no truncation) and a complete `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (5468 lines, single top-level key `scaffold_difficulty_design`, tail intact). Only `SCAFFOLD_CORNER_DESIGN.yaml` was absent — the prior run died between §1.8 and §1.9. Because nothing downstream existed yet (no PRD.md, no test_suite/, no implementation/), a full Step 2 re-run was *possible*, but it would have discarded a valid 5468-line §1.8 index that was generated against this exact SCAFFOLD.yaml and replaced it with a §1.8 built against a different SCAFFOLD.yaml — pure loss with an added cross-artifact-consistency risk. Decision: treat the two existing files as frozen inputs and generate only the missing §1.9. Subagent was explicitly forbidden from modifying either frozen file, and both were confirmed byte-unchanged on exit.

Subagent summary (verbatim):

Done. `SCAFFOLD_CORNER_DESIGN.yaml` (§1.9, breadth index) is written at `/home/ubuntu/github/CodingPRD/tasks/task_2411_household_staff_placement_agency/SCAFFOLD_CORNER_DESIGN.yaml` — 18,954 lines. The two frozen inputs are byte-unchanged (`SCAFFOLD.yaml` still 3798 lines, `SCAFFOLD_DIFFICULTY_DESIGN.yaml` still 5468).

**Total instances: 181** (152 live recipes / 29 `excluded_because` stubs deferring to a named §1.8 depth instance).

Per-section counts:

| section | instances |
|---|---|
| entities | 16 |
| state_machines | 46 |
| calculations | 22 |
| validations | 51 |
| endpoints | 10 |
| errors | 5 |
| rbac | 15 |
| cross_cutting_complexity_layers | 14 |
| consistency_model | 2 |

**Parse confirmation:** the brief's one-liner prints `OK sections: 9` — the file loads as valid YAML with exactly the single top-level key `scaffold_corner_design`.

Validation performed before exit:
- `scaffold_lint.py` verdict: **clean lint** — all 3091 calls across §1.8+§1.9 conform to the §1.5 endpoint contract (endpoint declared, role permitted, payload keys ⊆ declared input with required fields present, captures resolve to §1.1 output fields, OCC fields templated), and every §1.1 FK has reverse-reachability in §1.5. The last two flagged items were the deliberately negative/auth-exempt triggers; renaming them to `the_clock_read_with_missing_auth_headers_echoes_the_stored_time` (endpoints) and `the_error_envelope_for_a_missing_required_field_carries_the_declared_shape` (errors) brings them under the linter's negative-trigger waiver, which is the intended convention rather than a change of test content.
- All 181 names unique, and disjoint from the 28 §1.8 instance names; every cited `difficulty_instance` exists in §1.8.
- Every `ERR_*` id referenced exists verbatim in `SCAFFOLD.yaml`; all 73 catalogue error ids are triggered by §1.8 ∪ §1.9 (`never triggered: []`). No undeclared endpoint paths. No YAML anchors/aliases leaked; stubs carry no `test_recipe`, live instances carry exactly `setup_api_calls`/`trigger`/`asserts`.

## Step 3: Copy shared files — 2026-09-02T13:47:00.000Z

Copied `INSTRUCTION.md` from the project root to `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-02T14:06:00.000Z

Orchestrator verification before accepting: `PRD.md` is 477 lines, opens with `# Household Staff Placement API — Product Requirements Document`, and terminates on a closed §5 error-catalogue table row (`| ERR_CLOCK_NOT_MONOTONIC | 422 |`) — no mid-section truncation. Top-level sections present at lines 3/11/168/326/401.

Subagent summary (verbatim):

The PRD is complete on disk at `/home/auburn/…` — full path: `/home/ubuntu/github/CodingPRD/tasks/task_2411_household_staff_placement_agency/workspace/PRD.md`.

## Result

**Final line count: 477 lines** (15,465 words).

**Top-level sections emitted (in order):**
1. `## 1. Introduction`
2. `## 2. Global Specifications & System-Wide Principles` — 12 subsections: 2.1 User and Role-Based Access Control · 2.2 API Response Structure (verbatim fixed block) · 2.3 Pagination · 2.4 Resource Identity, Timestamps and Versioning · 2.5 Nested Read Paths and Path-Parameter Resolution · 2.6 The Logical Clock and the Ops Sweep · 2.7 Money, Basis Points, Points and Rounding · 2.8 Optimistic Concurrency Control on Supersede Paths · 2.9 Cascade Discipline and Parallel State Dimensions · 2.10 Separation of Duties on the Vetting and Compliance Desks · 2.11 Validation Precedence · 2.12 The Household Receivable Ledger and the Credit Hold
3. `## 3. Business Logic & Workflows` — 9 subsections: 3.1 Household Intake, the Confidentiality Agreement and the Scoping Loop · 3.2 Fee Bands and the Resolution of the Placement Fee · 3.3 Candidate Vetting: References, the Reference Chain and the Background Fork · 3.4 Presenting Candidates: Trial Days and Working Interviews · 3.5 Negotiating Live-in Accommodation and the Working Schedule · 3.6 The Offer, the Confirmed Start and the Final Re-pricing · 3.7 Milestone Billing, the Payroll Handoff and the Household Ledger · 3.8 The Guarantee Window: Claims and the Pro-rated Refund · 3.9 Non-solicitation Enforcement, the Penalty and Reinstatement
4. `## 4. Endpoint Definitions` — 4-column table, **68 rows** (all scaffold endpoints, exact role lists)
5. `## 5. Error Code Catalogue` — 2-column table, **71 rows** (every scaffold error id); document ends here, no audit footer

**Document ends complete.** Last 3 lines:
```
| `ERR_NON_SOLICITATION_TERM_EXPIRED` | 422 |
| `ERR_SETTLEMENT_EXCEEDS_PENALTY` | 422 |
| `ERR_CLOCK_NOT_MONOTONIC` | 422 |
```

## Hard Contract reports

**Contract 1 — Field-Name Coverage: PASS.** Programmatically verified: all 126 distinct `entities[].fields[].name` values appear verbatim in backticks; all 92 distinct endpoint `input`/query-parameter identifiers appear verbatim in backticks; the four common fields (`id`, `created_at`, `updated_at`, `version`) plus `limit`/`offset` are covered. Zero misses.

**Contract 2 — Rule Coverage: PASS.** All 71 error ids appear in the prose body (§2/§3), not merely in the §5 table — verified programmatically, zero table-only ids. All 92 state-machine transitions across the 14 machines (including the parallel `Placement.placement_status`/`billing_status` and `Candidate.vetting_status`/`availability_status` dimensions, and the four self-loops `TRIALING→TRIALING`, `OFFER_PENDING→OFFER_PENDING`, `COUNTERED→COUNTERED`, `INCONCLUSIVE→INCONCLUSIVE`) are described with from/to, preconditions paired to error ids, and side effects including every cascade hop. All 4 OCC rules carry write endpoint + occ field + error id + 412. All 8 calculations are written as ordered natural-language steps with rounding points, half-open boundaries, tier keys and forbidden rearrangements. The full 48-rule validation ladder with `applies_to` scopes is rendered in §2.11 and re-stated per workflow. All 118 enum values across every enum-typed field appear in backticks (verified programmatically after adding the missing `CLIENT_WITHDRAWN` `void_reason` value).

**Contract 3 — §3 Path Purity: PASS.** Programmatically verified over every backtick token in the §3 range (lines 168–325): zero tokens begin with `/`, zero are bare HTTP methods, zero combine method+path. All §3 operations are framed as state transitions, role + action verb, or capability descriptions.

**Deliberate pinning decisions** (scaffold internal conflicts resolved once and applied consistently): validation-22 numeric bands declared authoritative over the narrower entity descriptive bands (`weekly_hours` 1–80, `days_off_per_week` 0–7, `fee_percent_bps` 1–10000, `guarantee_window_days` 1–365), with an explicit sentence saying so; `limit` documented as default 10 / min 1 / max served 100 with `ERR_INVALID_RANGE` outside 1–200; conditional-zero violations (`day_rate_cents` for `WORKING_INTERVIEW`, `imputed_accommodation_cents` when not live-in) pinned to `ERR_INVALID_RANGE`; negative `settlement_amount_cents` pinned to `ERR_INVALID_RANGE` (priority 22 outranks priority 97); `rerun_count` incremented only on the `INCONCLUSIVE→INCONCLUSIVE` self-loop. The scaffold's numeric worked examples were deliberately **not** reproduced — formulas are pinned by ordering, rounding point and boundary instead, so no assert-like constants leak into the implementer-facing prose.

## Step 5: Generate unit tests — 2026-09-02T16:22:00.000Z

Launched concurrently with Step 6 in a single assistant message, so the test generator and the implementation generator could not see each other's output directories (`test_suite/` did not exist when the impl agent started).

Subagent summary (verbatim):

The suite is complete. Both design queues are fully translated.

## Exit report

**Test files:** 21 (`test_suite/test_01_*.py` … `test_21_cross_cutting.py`), plus `test_suite/conftest.py`
**Total test functions:** 221 — collected cleanly by pytest (`221 tests collected`, 0 errors)

**Per-queue counts**

| Queue | Design instances | Instances translated | Tests emitted |
|---|---|---|---|
| A — §1.8 `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 28 live (0 stubs) | **28 / 28** | 69 |
| B — §1.9 `SCAFFOLD_CORNER_DESIGN.yaml` | 181 total, 29 `excluded_because` stubs → 152 live | **152 / 152** | 152 |

Queue A files: test_01–test_09 (≥2 tests per instance). Queue B files by section: entities 16 (test_10), state_machines 40 (test_11/12/13), calculations 15 (test_14), validations 41 (test_15/16/17), endpoints 10 (test_18), errors 5 + consistency_model 2 (test_19), rbac 15 (test_20), cross_cutting_complexity_layers 8 (test_21).

**Instances SKIPPED: none.** Every live instance in both indices passed the PRD-first two-condition filter. No test is marked skip/xfail and no placeholders were emitted.

**Audit results (all green)**
- 180 distinct `Design:` tags = 28 + 152; every tag resolves to a real instance; no untagged, dual-tagged, or stub-tagged test; the tag is the last docstring line in all 221 tests.
- All `PRD §x.y: "…"` citations verified verbatim against `workspace/PRD.md` (whitespace-normalised substring match).
- No "scaffold"/design vocabulary in emitted code; no unused `test_helpers` imports; per-file `test_NN_` numbering strictly sequential.

**`test_helpers/` inventory** (9 modules, 3,229 lines): `__init__.py` (barrel, also re-exports the `prd_bench_local_runner.testing` validators), `constants.py`, `types.py`, `api_errors.py`, `test_users.py`, `api_client.py`, `factories.py`, `fixtures.py`, `assertions.py`.

**Design-data corrections applied** (design values that contradict the PRD; the PRD-derivable value was asserted instead, intent preserved): `guarantee_expires_on` is stamped at offer creation so it reads `"2026-11-30"` on a `PENDING_ACCEPTANCE` placement, not `null` (3 instances); a requisition sits in `TRIALING` — not `OFFER_PENDING` — until an offer is actually extended (rbac term-response and cross-cutting stale-offer instances); the error envelope's `data` carries `error_id` + `message` rather than being `null`, and exact `message` strings were replaced by `error_id` because §5 publishes no message text; `invoicing_before_the_placement_is_active_is_refused` was retargeted from the `ENGAGEMENT` milestone (which §3.7 expressly permits at `PENDING_ACCEPTANCE`) to the `TRIAL_CLEARED` row; reference-overlap is 409, not 422; illegal `region_code`s drawn from the declared enum; `scope_items` `MVR`→`DMV`.

## Step 6: Generate implementation — 2026-09-02T16:22:00.000Z

Launched concurrently with Step 5 (same assistant message). The impl agent was forbidden from reading `test_suite/`/`test_helpers/`; physical isolation held because neither directory existed at its spawn time.

Subagent summary (verbatim):

Implementation for task 2411 (Household Staff Placement Agency) is complete and verified.

## File inventory (`/home/ubuntu/github/CodingPRD/tasks/task_2411_household_staff_placement_agency/workspace/implementation/`)

| File | Lines |
|---|---|
| `requirements.txt` | 1 |
| `start.sh` | 10 |
| `app.py` | 69 |
| `db.py` | 234 |
| `errors.py` | 112 |
| `middleware.py` | 55 |
| `response.py` | 68 |
| `timeutil.py` | 80 |
| `validation.py` | 240 |
| `services/__init__.py` | 0 |
| `services/calc.py` | 264 |
| `services/domain.py` | 437 |
| `routes/__init__.py` | 0 |
| `routes/billing.py` | 367 |
| `routes/candidates.py` | 268 |
| `routes/cases.py` | 246 |
| `routes/clients.py` | 169 |
| `routes/clock.py` | 43 |
| `routes/fee_schedules.py` | 114 |
| `routes/placements.py` | 422 |
| `routes/requisitions.py` | 215 |
| `routes/trials.py` | 405 |
| **total** | **4025** |

## Endpoint count
**68 implemented**, exactly matching the 68 `- method:` entries in `SCAFFOLD.yaml` / the PRD §4 table (verified by enumerating Flask's URL map and excluding HEAD/OPTIONS).

## Boot check: PASS
Fresh process on a random port (`PORT=29253 bash start.sh`, foreground, binds `0.0.0.0`):
- `GET /_clock` → `{"meta":{"api_request_id":"req_...","api_request_timestamp":"2026-09-02T14:41:20.438Z"},"response_type":"object","data":{"current_utc":"2026-08-01T00:00:00Z"}}` — correct object envelope, clock at the PRD default.
- `GET /clients` without headers → `401` (`ERR_MISSING_AUTH_HEADER`); with `AgencyPrincipal` headers → array envelope with `limit/offset/total_count/has_more` and `data: []`, confirming **zero seeded data**.
- Server killed cleanly; port released. No stray listeners remain.

## Coverage notes
- Storage is process-memory dicts only; a grep for `sqlite`, `open(`, `json.dump`, `pickle`, `shelve` returns nothing, so `start.sh` re-invocation wipes all state (required by `--isolation per-test-server`).
- `start.sh` installs Flask only when the import fails, avoiding pip contention across the 8 concurrent per-test reboots.
- All 14 state machines, 8 calculations, 71 error ids, the 9-tier validation precedence ladder, RBAC matrix (including the body-value-partitioned NDA endpoint), OCC on all 4 supersede paths with the 3 distinct 412s, the append-only ledger with running-balance fold and credit-hold gate, the waterfall milestone allocation with frozen/open partitions, dual-variant fee rounding, reference interval merge, and the two-part clock sweep are implemented — no stubs or TODOs.
- An end-to-end smoke run through the full lifecycle passed every assertion, including: provisional fee 3,600,000 → FINAL 3,700,000 with re-allocation `[1080000, 1122857, 1497143]` (frozen row untouched, sum exact); refund proration elapsed 2 / unused 88 / gross 3,617,778 / retained 361,778 / net 3,256,000; non-solicitation penalty 2,775,000 (base 3,700,000 in the [2M,5M) → 7500 bps tier) with maker≠checker enforcement, suspension cascade, settlement cap and reinstatement; ledger fold `[1080000, 0, 1497143, -1758857, 1016143, -983857]` with no `version`/`updated_at` on ledger rows.

## Step 7: Run tests and iterate — 2026-09-02T17:00:00.000Z

Stale `results.*.json` were removed before the first sweep. Orchestrator-side independent verification of the final sweep (`workspace/implementation/results.{1..8}.json`, mtime 16:43): every round reports `passed == total == 221`; `test_suite/` still holds 221 test functions, consistent with the subagent's "no deletions" claim. Baseline sweep was deterministic at 216/221 in all 8 rounds — the 5 failures were real defects, not the load-induced flakiness this host is prone to.

Subagent summary (verbatim):

Sweep is fully green. Exiting.

## Summary

**Iterations run: 2** (two full 8-round parallel sweeps under `setsid`, 221 tests × 8 rounds each).

- **Iteration 1**: 216/221 in all 8 rounds — **5 failures, identical in every round** (no flakiness; no `Terminated`/reaping artifacts, so no load-induced noise to discount).
- **Iteration 2**: **221/221 in all 8 rounds** (`{(221, 221, 0)}` was the only distinct outcome tuple).

### Tests deleted
None. No test asserted a scaffold-only rule; all five failures resolved to one mistranslated assertion class and two genuine artifact bugs.

### Assertions removed (STEP 1c partial-coverage handling)
- `test_suite/test_20_rbac.py` → `test_12_both_counterparties_answer_the_same_term`: dropped `assert accepted["last_responder_role"] == "CANDIDATE"`. **BRANCH-ASYMMETRIC SIDE EFFECT** — PRD §3.5 renders the `COUNTER` branch fully ("Each counter … sets `last_responder_role` to `CLIENT` or `CANDIDATE` according to the responding role") but enumerates the `ACCEPT` branch's effects (`live_in_required` write-back, `version` increment, `status` → `ACCEPTED`) without mentioning `last_responder_role`; the `REJECT` branch is likewise silent. Both readings are PRD-faithful, so the write pathway is not uniquely derivable. Scaffold provenance: `Corner/rbac/both_the_household_and_the_candidate_may_answer_a_term`. The rest of the test (both counterparties may answer; alternation; counter values retained; requisition state) is retained.

### Fixes applied to `test_suite/`
Three tests asserted a freshly-registered candidate's `screening_score` equalled its experience points, contradicting PRD §3.3 verbatim: *"A fresh candidate begins at `vetting_status` `UNVETTED` … with … `screening_score` and `placement_ready_score` all 0, and `version` 1."* §3.3 also enumerates the recompute triggers (reference recording, reference verification, background result, adjudication) — registration is not one. The suite was self-contradictory: `test_10`'s `test_07_a_new_candidate_defaults_live_in_willing_and_zeroes_every_counter` already asserted `screening_score == 0` on a fresh candidate and passed.
- `test_10_entity_invariants.py:481` — `test_14_years_experience_of_sixty_one_…`: `== 36` → `== 0` (also swapped the docstring's experience-points citation for the §3.3 initial-state sentence that actually governs).
- `test_16_validations_gates.py:209` — `test_05_an_unvetted_candidate_cannot_be_booked_for_a_trial`: `== 30` → `== 0`.
- `test_20_rbac.py:144` — `test_03_the_consultant_may_register_a_candidate_but_not_reference_it`: `== 30` → `== 0`.

### Fixes applied to `test_helpers/`
None — no fixture, factory or role-header helper constructed a PRD-inconsistent precondition.

### Fixes applied to `implementation/`
- `workspace/implementation/services/domain.py` → `cancel_trial()`: removed the `note` → `outcome_note` write. PRD §3.4 says cancellation takes the engagement *"to `CANCELLED` with the supplied reason stamped"* — it enumerates only the reason; `outcome_note` is created null (§3.4) and is owned by the record-outcome path. Persisting the cancel `note` into it was an untraceable side effect. Three other tests (`test_05:213`, `test_16:416`, `test_19:204`) already asserted `outcome_note is None` and only passed because their cancels carried no note.

No implementation check required by the PRD was removed or weakened, no endpoint/field/capability was added, and storage remains in-memory dicts only (verified: no `sqlite`/`json.dump`/`pickle`/`shelve`/file-`open` in the implementation tree), so `start.sh` re-invocation under `--isolation per-test-server` still wipes all state.

## Step 8: Finalize PRD — 2026-09-02T17:05:00.000Z

Skip condition not met (Step 7 ran 2 iterations with 1 `implementation/` fix, 3 `test_suite/` fixes and 1 assertion removal), so Step 8 ran. The Step 7 worklog entry above was inlined verbatim as `<step_7_diff>`.

Subagent summary (verbatim):

Done. `/home/ubuntu/github/CodingPRD/tasks/task_2411_household_staff_placement_agency/workspace/PRD_FINALIZED.md` written.

## Line counts
- PRD.md: 477 lines; PRD_FINALIZED.md: 477 lines — **0.0% line delta** (both patches are inline sentence insertions inside existing paragraphs; +2 sentences, ~76 words).

## Changes (one per `<step_7_diff>` item)

- **§3.5 (line 254, ACCEPT paragraph) — insert** — pinned that `ACCEPT` and `REJECT` leave `last_responder_role` untouched; only the opening proposal (`AGENCY`) and a `COUNTER` ever write it — `implementation/routes/trials.py:301, 374` (writes), `:386-403` (ACCEPT/REJECT branches, no write).
- **§3.4 (line 244, cancellation) — insert** — pinned that the cancel `note` is accepted but not persisted, and a cancelled engagement's `outcome_note` stays null (`outcome_note` is written only by record-outcome) — `implementation/services/domain.py:264-273`, `implementation/routes/trials.py:209-210`.
- **No edit for the three `screening_score` test fixes.** PRD §3.3 (line 200) already states verbatim that a fresh candidate has `screening_score` … all 0, and `implementation/routes/candidates.py:79` sets `"screening_score": 0` at registration with no recompute call. Pure test-fixture bug, not a PRD silence or mismatch.

## Per-edit pre-edit search log

**Edit 1 — subject: `last_responder_role` (every write/read of the field).**
(b) Enumerated via `grep -rn last_responder_role implementation/`: `routes/trials.py:301` (creation → `"AGENCY"`), `:359` (COUNTER alternation read), `:374` (COUNTER write), `:383` (ACCEPT alternation read, guarded by `was_countered`); ACCEPT branch `:386-397` and REJECT branch `:399-403` — neither writes the field. Also checked every other path that mutates an `AccommodationTerm` row, found via `grep -rn accommodation_terms implementation/`: the supersede loop in `routes/trials.py:286-289` (`→ SUPERSEDED`), the requisition-withdrawal cascade in `routes/requisitions.py:207-210` (`→ REJECTED`), and the read-only lookup in `routes/placements.py:228` — none touch `last_responder_role` either.
(c) Adjustment: my first phrasing was "only a `COUNTER` ever rewrites it", which would have been false against the creation write at `:301`; I widened it to "after the opening proposal stamps `AGENCY`, only a `COUNTER` ever rewrites that field", which is simultaneously true of the two system-driven terminal cascades (withdraw, supersede) that also leave the field alone.

**Edit 2 — subject: the trial-engagement `note`/`outcome_note` fields.**
(b) Enumerated via `grep -rn "outcome_note" implementation/` and `grep -rn cancel_trial implementation/`: `routes/trials.py:122` (created null), `:198/209-210` (record-outcome, the sole writer, and only when supplied), `:236/244` (cancel endpoint validates `note` then passes it), `services/domain.py:264-273` (`cancel_trial`, no `outcome_note` write); plus the three system cancel callsites `services/domain.py:395` (`CLIENT_SUSPENDED`), `routes/vetting.py:189` (`VETTING_FAILED`), `routes/requisitions.py:207` (`CLIENT_REQUEST`), all of which pass no note. Also checked `start_trial` (`routes/trials.py:170-189`), whose PRD-mentioned optional `note` is likewise never persisted — consistent with the new wording. Confirmed a cancelled row can never carry a non-null `outcome_note`, since record-outcome requires `IN_PROGRESS` and `PASSED`/`FAILED` are terminal against cancel (`:240-242`).
(c) Adjustment: avoided the word "ignored" (which would falsely imply no validation — the cancel path does type/length-check `note` via `require_string`, so a non-string is refused) and used "accepted but not persisted on the engagement" instead; scoped the null claim to cancelled engagements rather than to `outcome_note` generally, so the record-outcome writer at `:210` is not contradicted.

## Step 9: Complete PRD — 2026-09-02T17:25:00.000Z

Ran the full PRD-vs-`implementation/` completeness scan starting from `PRD_FINALIZED.md`. Orchestrator verification: `PRD_COMPLETED.md` is 477 lines and terminates on the closed §5 table (`| ERR_CLOCK_NOT_MONOTONIC | 422 |`) — structure preserved, no truncation.

Subagent summary (verbatim):

All edits are applied. `PRD_COMPLETED.md` is complete.

## Source vs. completed

| | `PRD_FINALIZED.md` | `PRD_COMPLETED.md` |
|---|---|---|
| lines | 477 | 477 |
| chars | 115,921 | 126,128 |

Char delta: **+10,207**. Structure untouched: no new sections, no new paragraphs, no new lines — all 46 changes are in-paragraph inserts or revisions across 46 existing lines.

**Counts: 36 ambiguity-pins, 10 mismatch-revisions (46 total).**

## Changes

- §2.1 — revise — mismatch — entity-backed `Client`/`Candidate` identity is convention only; no endpoint compares `X-User-ID` to a resource's `client_id`/`candidate_id`, so there is no ownership check at all — `middleware.py:34-55`
- §2.1 — revise — mismatch — "Two operations" partitioned by body → one; the 403 fires only on the literal `SIGN`/`COUNTERSIGN`, any other action string falls through to `ERR_INVALID_ENUM` — `routes/clients.py:98-108`
- §2.2 — insert — ambiguity — `api_request_id` is `req_` plus exactly 20 uppercase alphanumerics — `response.py:21-25`
- §2.2 — insert — ambiguity — `api_request_timestamp` is wall-clock, never the logical clock — `response.py:31`
- §2.3 — insert — ambiguity — `meta.limit` reports the *effective* capped limit; non-integer `limit`/`offset` → `ERR_INVALID_RANGE`; empty string = omitted — `validation.py:205-231`, `response.py:51-57`
- §2.3 — insert — ambiguity — identical `created_at` broken by creation order — `db.py:227-230`
- §2.4 — revise — mismatch — `version` advances at most once per row per request; rows created in the request stay at 1; a no-op recompute moves neither `version` nor `updated_at` — `db.py:204-219`
- §2.6 — insert — ambiguity — absent `current_utc` → `ERR_INVALID_REQUEST`; an instant equal to the stored clock is accepted and still sweeps; the caller's literal string is stored and echoed verbatim — `routes/clock.py:22-43`
- §2.11 step 2 — insert — ambiguity — wrong-JSON-type mapping: numeric field → `ERR_INVALID_RANGE`, string/bool/array field → `ERR_INVALID_REQUEST` — `validation.py:42-124`
- §2.11 step 5 — revise — mismatch — terminality is evaluated **before** the endpoint's specific state error, not below it — `routes/requisitions.py:167-170`, `routes/billing.py:210-214`
- §2.12 — insert — ambiguity — five workflow entry types carry a server-composed `memo`; `PENALTY_SETTLED` carries the settling caller's optional one — `services/domain.py:360-367`, `routes/billing.py:97`, `routes/cases.py:228`
- §3.1 — insert — ambiguity — `signatory_name` optional (1–120, null when omitted) and ignored on `COUNTERSIGN` — `routes/clients.py:107-118`
- §3.1 — revise — mismatch — `first_year_compensation_cents` floor of 100,000 is descriptive; only non-negative is enforced; opening `scope_note` optional — `routes/requisitions.py:51-54`
- §3.1 — insert — ambiguity — scope round: other non-terminal states → `ERR_INVALID_STATE_TRANSITION`, terminal → `ERR_ENTITY_TERMINAL`, `ONBOARDED` expressed as NDA-then-suspension; `scope_note` required — `routes/requisitions.py:119-141`
- §3.1 — revise — mismatch — finalize-scope on `PLACED`/`WITHDRAWN` → `ERR_ENTITY_TERMINAL`, not `ERR_REQUISITION_NOT_SCOPING`; `note` not persisted — `routes/requisitions.py:163-170`
- §3.1 — insert — ambiguity — withdraw `reason` accepted but not persisted — `routes/requisitions.py:190-192`
- §3.2 — insert — ambiguity — both band edges non-negative; retire `reason` not persisted — `routes/fee_schedules.py:41-42,105-108`
- §3.2 — insert — ambiguity — identical `created_at` in a band tie → publication order — `services/calc.py:72-74`
- §3.3 — revise — ambiguity — `verification_note` written only when supplied (stated once as the general rule for optional notes) — `routes/vetting.py:82-83`
- §3.3 — revise — mismatch — `findings_note` written only when supplied, so a re-recorded `INCONCLUSIVE` screen keeps its prior note — `routes/vetting.py:132-133`
- §3.3 — insert — ambiguity — `waiver_note` only when supplied; `FAIL` stamps the same actor and note fields as `PASS` — `routes/vetting.py:168-171`
- §3.3 — insert — ambiguity — release `note` not persisted; a null `cooling_off_until` releases unconditionally — `routes/candidates.py:249,261-263`
- §3.4 — revise — mismatch — trial start checks `vetting_status` **before** the clock, so a rejected candidate outranks `ERR_TRIAL_NOT_STARTED`; `note` not persisted — `routes/trials.py:172-185`
- §3.4 — insert — ambiguity — `outcome_note` written only when supplied — `routes/trials.py:198,208-210`
- §3.4 — insert — ambiguity — the `FAILED` restore also requires `vetting_status` ≠ `REJECTED` — `services/domain.py:247-252`
- §3.4 — insert — ambiguity — the cancel-path `TRIALING → SOURCING` fallback also requires no `PENDING_ACCEPTANCE` placement — `services/domain.py:219-231`
- §3.5 — insert — ambiguity — `note` is stored on the term; terminality is the only parent state test and no household gate applies, so a proposal is admissible from any non-terminal requisition state — `routes/trials.py:264-302`
- §3.5 — revise — mismatch — `ACCEPT`/`REJECT` discard supplied package values and re-check the stored `live_in`; `note` overwrites on all three responses; `REJECT` is exempt from alternation, the round cap and the live-in re-check — `routes/trials.py:379-403`
- §3.6 — insert — ambiguity — an offer on a requisition with no resolved snapshot → `ERR_NO_FEE_SCHEDULE_MATCH`, tested after the credit hold — `routes/placements.py:114-119`
- §3.6 — revise — mismatch — confirm-start re-resolves the band **before** the accepted-accommodation gate; `note` not persisted — `routes/placements.py:219-231`
- §3.6 — insert — ambiguity — terminate `reason` validated but not persisted — `routes/placements.py:266`
- §3.7 — insert — ambiguity — invoice `note` not persisted — `routes/billing.py:61`
- §3.7 — insert — ambiguity — `payment_reference` required but accepted as any string, including empty — `routes/billing.py:113`
- §3.7 — insert — ambiguity — reverse `reason` not persisted; `billing_status` judged only from its current value, so `FULLY_BILLED` sticks through a later reversal — `routes/billing.py:149`, `services/domain.py:321-336`
- §3.7 — insert — ambiguity — handoff field lengths; opening `ein_status` may be any of the three; the exists-check ignores the first handoff's status and the placement's state; `update-ein` refuses `NOT_APPLIED` with `ERR_INVALID_ENUM` and permits `ISSUED → APPLIED` — `routes/placements.py:402-409`, `routes/billing.py:335-341`
- §3.7 — insert — ambiguity — ledger `memo` 1–200; the response resource is the `LedgerEntry`, not the household — `routes/clients.py:137,152`
- §3.8 — insert — ambiguity — `narrative` 1–2000 characters — `routes/placements.py:347`
- §3.8 — insert — ambiguity — filing has no placement-state or terminality gate beyond the two guarantee tests — `routes/placements.py:352-365`
- §3.8 — insert — ambiguity — `OPEN_REVIEW` and `REQUEST_INFO` state violations also report `ERR_CLAIM_NOT_UNDER_REVIEW`; `decision_note` only when supplied; `info_note` required and appended after a newline — `routes/billing.py:212-214,317-318`
- §3.8 — insert — ambiguity — `REFUND_ISSUED` is appended even when `net_refund_cents` is 0 — `routes/billing.py:287-294`
- §3.9 — insert — ambiguity — `allegation_note` 1–2000 characters — `routes/cases.py:48`
- §3.9 — insert — ambiguity — investigate `note` not persisted — `routes/cases.py:103`
- §3.9 — revise — ambiguity — `findings_note` stamped only when supplied — `routes/cases.py:162-163`
- §3.9 — insert — ambiguity — the suspension-cascade hop five also requires no `PENDING_ACCEPTANCE` placement — `services/domain.py:219-231,400`
- §3.9 — insert — ambiguity — settle `memo` 1–200, carried onto the `PENALTY_SETTLED` row and null there when omitted — `routes/cases.py:206,228`
- §4 preamble — insert — ambiguity — unserved path → `ERR_INVALID_REQUEST` at 404, wrong method → `ERR_INVALID_REQUEST` at 405, trailing slash ignored — `app.py:27,48-54`

Two cross-checks came back clean and needed no edit: all 68 served routes match the §4 table's paths and role sets exactly, and the implementation's error catalogue is set-identical to §5 (71 ids each, no divergence).
