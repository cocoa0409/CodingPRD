# Worklog — task_2735_lateral_partner_hiring_portable_business_diligence

## Step 1: Create task directory — 2026-09-04T13:33:56.307Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2735_lateral_partner_hiring_portable_business_diligence` and its `workspace/` subdirectory. Index 2735 was pre-assigned by the orchestrating command (no ./tasks/ scan, no auto-allocation) because up to 32 pipelines run concurrently on this host.

## Step 2: Generate Scaffold — 2026-09-04T15:53:38.149Z

All three scaffold artifacts are complete and the lint is clean.

**Lint verdict (verbatim):**
```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           /home/ubuntu/github/CodingPRD/tasks/task_2735_lateral_partner_hiring_portable_business_diligence/SCAFFOLD.yaml
  Difficulty design:  /home/ubuntu/github/CodingPRD/tasks/task_2735_lateral_partner_hiring_portable_business_diligence/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      /home/ubuntu/github/CodingPRD/tasks/task_2735_lateral_partner_hiring_portable_business_diligence/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    70
  §1.1 entities declared:     16
  §1.8 instances scanned:     26
  §1.9 instances scanned:     65
  Calls scanned (§1.8+§1.9):  1718

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

**Files** (all in `/home/ubuntu/github/CodingPRD/tasks/task_2735_lateral_partner_hiring_portable_business_diligence/`):
- `SCAFFOLD.yaml` — 3,383 lines / 173 KB
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 3,185 lines / 237 KB
- `SCAFFOLD_CORNER_DESIGN.yaml` — 6,950 lines / 495 KB

**SCAFFOLD.yaml (§1.0–§1.7)** — top-level keys are exactly `scenario, domain_name, api_prefix, response_envelope, complexity_profile, entities, state_machines, concurrency_rules, calculations, validations, endpoints, errors, roles`; neither `scaffold_difficulty_design` nor `scaffold_corner_design` is present. Counts: **16 entities, 13 state machines, 2 concurrency rules, 11 calculations, 29 ordered validations, 70 endpoints, 62 errors, 7 roles**. Profile: `expert_plus`, archetype `multi_party_negotiation` + `compliance_audit`, layers `cascading_side_effects / dual_variant_calculation / derived_field_reconciliation / optimistic_concurrency`, graph topology, cyclic state machines, `segregation_of_duties` role model, immediate consistency.

**SCAFFOLD_DIFFICULTY_DESIGN.yaml (§1.8)** — single top-level key; all nine §0.5 rules, **26 instances**: dual_variant_calc 3, combinatorial_formula 3, non_linear_state_machine 3, transitive_cascade 2, priority_pair_validation_conflict 3, boundary_precision_check 3, cross_entity_state_dependency 3, resource_temporal_overlap 3, compensating_invariant 3.

**SCAFFOLD_CORNER_DESIGN.yaml (§1.9)** — single top-level key; all nine sections, **96 instances (65 real recipes + 31 `excluded_because` stubs)**: entities 12/0, state_machines 11/7, calculations 3/11, validations 9/4, endpoints 5/0, errors 15/6, rbac 5/0, cross_cutting_complexity_layers 4/2, consistency_model 1/1. All 122 instance names across both design files are unique; every stub cites an existing `rule_id / instance_name` pair.

**Coverage caveats:**
- `bulk_action` (endpoints section) is deliberately omitted — §1.5 declares no bulk/batch endpoint to probe, so there is nothing to claim against.
- `calculations` and `state_machines` lean heavily on stubs (11/14 and 7/18) because most of their corner claims are already fully walked by §1.8 instances (the valuation dual-basis, the five-hop waiver cascade, the terminal-reentry machines); the stubs cite those instances rather than duplicating ~2,000 lines of recipe.
- Final cleanup this pass: normalized non-resolving `grounds` tokens (`concurrency_rules[...]` → dot form, `roles[CommitteeChair]` → `roles.CommitteeChair`, `envelope.pagination_fields` → `response_envelope.pagination_fields`, `complexity_layers.soft_delete` → `entities.LateralQuestionnaire.fields.entry_count` since `soft_delete` is not a declared layer, `roles.Candidate.entity_backed` → `roles.Candidate.identity`) — 7 replacements across the two design files. Earlier in the run I also fixed a duplicate `side_effects:` key in SCAFFOLD.yaml (Candidate `OFFER_OUT → WITHDRAWN`) that `yaml.safe_load` was silently swallowing along with the reservation-release cascade hops.

## Step 3: Copy Shared Files — 2026-09-04T15:53:57.137Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` to `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-04T16:12:00.000Z

PRD complete and verified.

**Output:** `workspace/PRD.md` — **503 lines**, written incrementally (1 `Write` + 8 heredoc appends + 3 small `Edit` fixes); ends cleanly on the last row of the §5 error table, no audit footer, no truncation.

**Section list**
- `# Lateral Partner Hiring API — Product Requirements Document`
- `## 1. Introduction`
- `## 2. Global Specifications & System-Wide Principles` — 2.1 Role-Based Access Control · 2.2 API Response Structure (fixed block, byte-verified) · 2.3 Pagination · 2.4 Resource Identity, Timestamps and the Logical Clock · 2.5 Money, Shares and Rounding Discipline · 2.6 Version Pinning on Diligence Writes · 2.7 Immediate Consistency and Multi-Hop Cascades · 2.8 Conserved Quantities · 2.9 Segregation of Duties · 2.10 Rejection Precedence · 2.11 Nested Path Resolution and Soft-Deleted Rows
- `## 3. Business Logic & Workflows` — 3.1 Practice Groups, Search Firms and the Exclusivity Calendar · 3.2 Confidential Sourcing and the Candidate Record · 3.3 The Lateral Partner Questionnaire and the Disclosed Client Book · 3.4 Collection Evidence and Portable-Business Validation · 3.5 Conflicts Clearance, Waiver Strategy and Matter Declination · 3.6 Offer Modelling, Committee Negotiation and the Hire · 3.7 Integration Planning, Onboarding Capacity and Cross-Selling · 3.8 Post-Hire Performance Tracking
- `## 4. Endpoint Definitions` (70-row table)
- `## 5. Error Code Catalogue` (62-row table)

**Coverage (machine-checked against SCAFFOLD.yaml)**
- **70/70 endpoints**; all 5 method/status combinations respected (15 × 201 creates, 55 × 200).
- **62/62 errors** with scaffold HTTP status (32×409, 16×404, 7×422, 2×403, 2×412, 401, 400, 402).
- **11/11 calculations** — all output fields and constants present; `net_first_year_economics` constants written as exact numerals (`50000.00`, `35000.00`, `0.04`, `500000.00`, `0.10`, `0.05`).
- **13/13 state machines** — every declared state present; all 74 transitions covered (34 in grouped/creation form, e.g. five-source `→ LAPSED`, four-source `→ WITHDRAWN`).
- **29/29 validations** — explicit precedence ladder in §2.10 with each error ID and each `applies_to` path.
- **7/7 roles**; **16/16 entities**.

**Hard Contracts**
- **Contract 1 Field-Name Coverage — PASS.** 145 required identifiers (133 entity fields + 22 request/query/path/OCC identifiers, deduped); 0 missing.
- **Contract 2 Rule Coverage — PASS.** Priorities 1–29 in order; both OCC rules with write + field + error + 412; cross-entity side effects hop-numbered (4-hop withdrawal, 5-hop waiver refusal/expiry); `applies_to` endpoint sets enumerated per validation; sibling branches given symmetric density.
- **Contract 3 §3 Path Purity — PASS.** 0 URL/method tokens in §3; all URLs confined to §2.10, §2.11, §4, §5.

**Hard constraint honoured:** neither design yaml was opened, grepped, or referenced.

**Scaffold inconsistencies resolved** (entity defaults / state machines treated as authoritative): engagement-create `fee_basis`/`fee_amount_usd` written as `NONE`/`0.00` rather than null; entry-create portable amounts as `0.00` rather than null; assessment lookback stated as "three calendar years, equivalently thirty-six months"; offer `counter` documented as departing `COMMITTEE_REVIEW` or `REPRICE_REQUIRED` per the state machine, not the endpoint `purpose` text; the garbled finalize side-effect replaced with the `committee_quorum_tally` rule (approvals × 3 ≥ 2 × (approvals + rejections)).

**Orchestrator truncation check:** `tail -15` ends on the final `ERR_GUARANTEE_BUDGET_EXCEEDED | 402` table row — a real section boundary, not mid-sentence. Machine re-verification by the orchestrator confirmed 62/62 error ids and 70/70 endpoint paths literally present in PRD.md. No regeneration needed.

## Step 5: Generate Unit Tests — 2026-09-04T17:38:38.801Z

Test generation is complete and verified. Everything lives at the task root — nothing was written under `workspace/`, and `workspace/implementation/` was never read or listed.

## Output

`test_helpers/` — 9 modules, 2,955 lines: `types.py`, `api_errors.py`, `api_client.py` (70 endpoints), `test_users.py`, `constants.py` (pre-derived SLIM/AB/FULL book and offer expectations), `assertions.py` (money/ratio/ISO-instant canonicalising comparators), `factories.py`, `fixtures.py` (lifecycle builders through hired/active-plan), `__init__.py` (flat re-export).

`test_suite/` — `conftest.py` + 22 test modules, 6,779 lines, **117 tests collected** (`pytest --collect-only -q` → `117 tests collected in 0.81s`; `py_compile` clean on all 31 files).

Per-file counts: entity_contracts 12; composite_valuation_and_offer_formulas 6; conserved_identities 6; cross_entity_prerequisites 6; dual_valuation_and_fee_bases 6; inclusive_boundaries 6; nonlinear_lifecycles 6; rejection_precedence_pairs 6; state_machine_transitions 6; temporal_overlap_windows 6; state_machine_cascades 5; cross_cutting_layers 5; endpoint_contracts 5; error_taxonomy 5; offer_lifecycle_errors 5; plan_and_book_errors 5; role_boundaries 5; declination_cascades 4; conflict_clearance_validations 3; valuation_scope_and_fee_clamp 3; committee_roll_validations 2; prior_firm_slot_restrictions 2; uniqueness_and_window_validations 2.

## Design-index accounting (machine-checked against both yamls)

- Queue A (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`): 26 instances across 9 rules, 0 stubs — **26/26 translated**, 2 tests per instance (52 tests).
- Queue B (`SCAFFOLD_CORNER_DESIGN.yaml`): 96 instances, 31 carrying `excluded_because` — **65/65 live instances translated**, 1 test each. Coverage by section: entities 12/12, state_machines 11/11, calculations 3/3, validations 9/9, endpoints 5/5, errors 15/15, rbac 5/5, cross_cutting_complexity_layers 4/4, consistency_model 1/1.
- Cross-check results: 0 tags pointing at a non-existent instance, 0 tags pointing at one of the 31 stubs, 0 live instances left untranslated, every test has exactly one trailing `Design:` line (117 tests / 117 tags).
- Skips: **no instance was skipped for PRD-coverage reasons.** The only untested instances are the 31 design-declared stubs (state_machines 7, calculations 11, validations 4, errors 6, cross_cutting 2, consistency_model 1), which by contract receive no tests.
- Citation gate: 315 docstring citation fragments re-checked against `workspace/PRD.md` — all verbatim.

## Adjudications worth passing to the implementation/finalize steps

Four design-index assertions contradict PRD.md; the generator followed the PRD and omitted or corrected the assertion rather than encoding the index:

1. `plan_abandon_returns_the_onboarding_slot_only_when_the_plan_was_active` expects `introduction_count == 1` after cancellation; PRD line 345 decrements it to 0 → assertion omitted.
2. `conflict_check_create_starts_pending_and_opens_the_clearance_dimension` expects `resolution_note == ""`; PRD line 260 says null → asserted `is None`.
3. `search_fee_is_clamped_by_the_engagement_fee_cap_at_hire` expects `guarantee_true_up_amount_usd == 80000.00`; the PRD waterfall yields 0.00 (net = −1,199,018.73) → true-up not asserted.
4. `assessment_ignores_unverified_out_of_window_and_withdrawn_book_rows` expects `verified_record_count == 3`; PRD line 226 counts every HISTORICAL+VERIFIED record with no window filter → asserted 5, with line 226 quoted.

Also carried forward: `POST /offers/{offer_id}/counter` is internally inconsistent in the PRD (§4 table lists `APPROVED -> COUNTER_REQUESTED`, §3.6 line 321 permits a counter only from `COMMITTEE_REVIEW` / `REPRICE_REQUIRED`). The §3.6 prose governs the suite, and no test asserts either behaviour for counter-from-APPROVED.

One environment note: `/tmp/verify_quotes.py` was overwritten mid-session by a concurrent agent working on task_2728; the gate now lives at `/tmp/verify_quotes_2735.py` and is task-pinned.

**Orchestrator layout check:** `test_helpers/` (9 .py) and `test_suite/` (24 .py incl. conftest) are at the task root; no `workspace/test_helpers` or `workspace/test_suite` strays exist.

## Step 6: Generate Implementation — 2026-09-04T17:38:38.801Z

Implementation is complete and verified.

## Location
`workspace/implementation/`

## Modules (2868 lines total)

| File | Lines | Role |
|---|---|---|
| `start.sh` | 10 | `cd`s to its own dir, guarded pip install (only when flask is missing, to avoid boot contention across 8 concurrent rounds), `exec python3 app.py` |
| `requirements.txt` | 1 | `flask==3.0.3` |
| `app.py` | 85 | Flask app, 6 blueprints, one global RLock per request (atomicity), ApiError/404/405/HTTPException/Exception handlers all returning the error envelope, binds `0.0.0.0:$PORT` (default 10000) |
| `errors.py` | 81 | `ERROR_STATUS` for all 63 catalogued codes + `ApiError` |
| `response.py` | 65 | `req_` id generator, `iso3` (exactly 3 fractional digits), object/empty/array/error envelopes |
| `db.py` | 120 | In-memory `Store` of 16 dicts, logical clock, `new_row`, write-if-changed `set_fields`, `pub` serialisation |
| `middleware.py` | 235 | Auth (401/403), body parse, all typed validators, pagination and query coercion |
| `lookups.py` | 113 | 16 existence resolvers (404) + relationship helpers |
| `calculations.py` | 164 | All constants, `r2`/`r4`/`floor2`, baseline, variance, concentration grading, haircut, adjusted total, rate alignment, expected contribution, declination split, quorum, approval, performance flag |
| `services.py` | 314 | Conserved-quantity recomputations (`sync_group_ledger`, `sync_vote_counters`, `sync_plan_counters`, `sync_group_onboarding`, `sync_firm_engagement_count`, entry counts), staleness propagation, offer economics |
| `cascades.py` | 143 | Clock sweeps (engagement expiry → waiver expiry → plan completion), withdrawal cascade, declination cascade, plan closure |
| `listing.py` | 24 | Deterministic `(created_at, _seq)` ordering, filters, paging |
| `routes/config.py` | 236 | Practice groups, search firms, engagements, `_clock/set_current_utc` |
| `routes/candidates.py` | 228 | Candidates + questionnaire lifecycle |
| `routes/book.py` | 216 | Client book entries, collection records, portability assessments |
| `routes/conflicts.py` | 223 | Conflict checks, waivers, matter declinations |
| `routes/offers.py` | 295 | Offers (create/patch/submit/finalize/counter/accept) + committee votes |
| `routes/integration.py` | 314 | Integration plans, introductions, performance reviews |

## Endpoint coverage: 70/70
`app.url_map` enumerates exactly 70 non-static rules, one per row of the PRD endpoint table (verified name-by-name, not just a count).

## Smoke tests: 3 suites, 0 failures
Run against a self-chosen port 18735, launched via `PORT=18735 bash start.sh`, shut down each time by its own PID only (no pattern kill was ever used).

- **Suite 1 (60 assertions)** — full happy path config → candidate → questionnaire → book → assessment → conflicts → offer → votes → finalize → accept → hire → plan → introduction → review, plus pagination and 400/401/403/404/409/422 paths. Money figures hand-checked against the PRD formulas (baseline 540000.00, variance_pct 0.325, top share 1.0 → HIGH → 0.15 haircut, adjusted 459000.00, expected contribution 454410.00, DIRECT_PLACEMENT fee 237500.00, net −856090.00, review `period_days` 31 / `plan_target` 38593.73 / attainment 3.1093 → ON_PLAN).
- **Suite 2 (38 assertions)** — odd-cent declination split `[180000.16, 180000.15]` summing exactly to the entry baseline with the whole remainder on `matter_types[0]`; `validated + declined == gross` invariant before and after; full rescission reversal chain; both OCC 412 codes; staleness → `REPRICE_REQUIRED` with votes voided `[1,0,1]`, reservation released, round and voter roll untouched; counter → round 2 → PATCH redraft → submit blocked by `ERR_ASSESSMENT_STALE`; simultaneous waiver-expiry and engagement-expiry sweeps in one clock move; post-deadline grant → `ERR_WAIVER_INVALID_STATE`.
- **Suite 3 (16 assertions)** — guarantee-budget boundary (1000000.01 → 402 `ERR_GUARANTEE_BUDGET_EXCEEDED`, exactly 1000000.00 → accepted, available driven to 0.00); 4-hop withdrawal cascade; approval with an abstention; onboarding capacity 409 on the second activate; plan-completion sweep; abandon rejected on a COMPLETED plan and for a non-owner.

Constraints honoured: no file/SQLite/JSON persistence anywhere (a fresh process reports all 16 collections empty and the clock at the default `2026-08-01T00:00:00Z`); nothing seeded, preloaded or hardcoded; `test_helpers/`, `test_suite/`, both SCAFFOLD design files and all sibling `task_*/` directories were never read; smoke scripts live in `/tmp`, not in the task dir; `__pycache__` removed.

## Step 7: Run Tests and Iterate — 2026-09-04T17:59:56.416Z

Clean 8-round sweep confirmed: 117/117 in every round.

## Summary

**Iterations run:** 2 (iteration 1: 109/117 in all 8 rounds, identical 8 failures — fully deterministic, no flakiness; iteration 2: 117/117 in all 8 rounds).

**Tests deleted:** none. All 8 failures traced to test-artifact bugs under STEP 2 (fixture/setup requests inconsistent with PRD, and one wrong expected status), so no assertion was weakened and no coverage was lost.

**Fixes applied to `test_helpers/`:**
- `test_helpers/fixtures.py` — added the missing `create_performance_review_payload` import from `.factories`; `add_performance_review()` called it at line 631 without importing it, raising `NameError` and killing both performance-review tests in `test_dual_valuation_and_fee_bases.py`.

**Fixes applied to `test_suite/`:**
- `test_declination_cascades.py` — `_setup_reprice_scenario()` validated the waiver create with the default `expected_status=200`; PRD §4 says "an endpoint that brings a brand-new resource row into existence answers `201`", and the rest of the suite already expects 201 for this endpoint. Added `expected_status=201`. This single glue bug failed all 4 tests in the file.
- `test_valuation_scope_and_fee_clamp.py::test_the_assessment_reads_only_verified_in_window_historical_rows_on_active_entries` — the setup created and soft-deleted the decoy `Ridgeline Foods` entry while the LPQ sat in `UNDER_REVIEW`. PRD only makes the book mutable in `DRAFT` and, per §3.3, "makes the client book mutable again — while the LPQ sits in `REVISION_REQUESTED`, entries may be created and soft-deleted"; nothing in PRD permits mutation from `UNDER_REVIEW`, so the implementation's refusal is faithful. Rebuilt the setup to disclose and prune the book while the LPQ is `DRAFT`, then walk `DRAFT → SUBMITTED → UNDER_REVIEW` before the assessment. All assertions unchanged.
- `test_cross_cutting_layers.py::test_a_withdrawn_row_still_resolves_with_its_evidence_but_leaves_the_next_valuation` — same root cause: soft-deleted entry B while `UNDER_REVIEW`. Rerouted through the PRD's own bounded revision loop (`request-revision` → soft-delete from `REVISION_REQUESTED` → `submit` → `start-review`) so the second assessment still runs from `UNDER_REVIEW`. All assertions unchanged (the first assessment still ends `SUPERSEDED` with `gross_baseline_total_usd` intact, second has `entry_count_in_scope == 1`, questionnaire `entry_count == 1`).

**Fixes applied to `implementation/`:** none. No implementation defect was found; `routes/book.py`'s `MUTABLE_BOOK = ("DRAFT", "REVISION_REQUESTED")` guard is the PRD-faithful reading and was deliberately left in place rather than relaxed to accommodate the fixtures.

**Notes for the record:** the generator's four flagged design-index divergences (plan_abandon `introduction_count`, conflict_check `resolution_note` null, search-fee guarantee true-up 0.00, assessment `verified_record_count` with no window filter) and the §3.6-governed `counter` source states all passed as-is — no action needed. `worklog.md` was not touched by the subagent.

**Orchestrator verification of sweep artifacts:** all 8 `workspace/implementation/results.{1..8}.json` exist (~37 KB each, written 17:53) and each reports `passed=117 / total=117 / failed=0`. The clean-sweep claim is independently confirmed, not taken on the subagent's word.

## Step 8: Finalize PRD — 2026-09-04T18:08:53.396Z

Step 8 ran (not skipped): Step 7 applied 1 `test_helpers/` fix and 3 `test_suite/` fixes, so the skip condition (zero iterations beyond baseline) did not hold.

## Line counts
- `PRD.md`: 503 lines / 111,336 bytes
- `PRD_FINALIZED.md`: 503 lines / 111,763 bytes
- Line delta: 0 (0.0%); byte delta +427 (+0.38%). One sentence revised in place, no sections added.

## Changes
- **§3.3 (The Lateral Partner Questionnaire and the Disclosed Client Book), soft-delete paragraph** — *revise* — the vague clause "only while the questionnaire's `status` permits mutation" now names the mutable set exhaustively (`DRAFT`, `REVISION_REQUESTED`) and states that both entry creation and soft-delete are refused with `ERR_QUESTIONNAIRE_INVALID_STATE` in `SUBMITTED`, `UNDER_REVIEW`, `ACCEPTED`, `ABANDONED` — `implementation/routes/book.py:18` (`MUTABLE_BOOK`), enforced at `:41-42` and `:94-95`.

## Per-edit pre-edit search log

**Edit 1 — book mutability window**
- (a) Subject: which questionnaire statuses permit client-book mutation, for both the create-entry and soft-delete endpoints, and the error raised otherwise.
- (b) Paths enumerated: grepped the whole `implementation/` tree for `MUTABLE_BOOK`, `ERR_QUESTIONNAIRE_INVALID_STATE`, `WITHDRAWN`, `client_book_entries[`. Read `routes/book.py` in full (`create_entry` :21-65, `delete_entry` :87-101 — the only two writers of entry `status`, both gated on the same `MUTABLE_BOOK` tuple; `create_assessment` :162-200 gated separately on `UNDER_REVIEW`/`ACCEPTED`; `list_entries` :74-84 hides `WITHDRAWN` by default). Read `routes/candidates.py:110-229` for the reachable questionnaire status lattice (`DRAFT`, `SUBMITTED`, `UNDER_REVIEW`, `REVISION_REQUESTED`, `ACCEPTED`) plus `ABANDONED` written by `cascades.py`. Read `routes/conflicts.py:20-60` to confirm the conflict-check gate (`UNDER_REVIEW`/`REVISION_REQUESTED`/`ACCEPTED`) is a distinct guard the wording must not bleed into.
- (c) Adjustments: (i) enumerated the four refusing statuses explicitly rather than "any other status", since `ABANDONED` is reachable only via the withdrawal cascade and the claim should be exactly the impl's complement set; (ii) worded the refusal as covering "creating an entry and soft-deleting an entry" only — deliberately not "any write to the book" — so it does not falsely capture `create_collection_record` (no questionnaire-status guard) or `create_assessment` (requires the opposite window); (iii) said nothing about guard ordering, leaving the §2.10 ladder and the impl's ownership-before-status order intact, and nothing about repeat deletes, so the idempotent 200 on an already-`WITHDRAWN` entry (`book.py:96-97`) is not contradicted; (iv) kept the pre-existing §3.3 sentence about `ACCEPTED` freezing the book verbatim — the new sentence is a strict superset.

## Items deliberately left unedited
- **`test_helpers/fixtures.py` missing import** — pure test-artifact `NameError`, no behavioral claim in PRD involved.
- **Waiver-create `expected_status=201`** — already uniquely determined by PRD §4's blanket 201-on-creation rule; `routes/conflicts.py:120` returns 201, so PRD prose stays verbatim.
- **The four flagged design-index divergences and the §3.6 `counter` source states** — Step 7 confirmed they pass as-is; no PRD-silence or mismatch surfaced.

**Orchestrator verification:** `diff PRD.md PRD_FINALIZED.md` shows exactly one changed line (line 224, the §3.3 soft-delete paragraph) — a genuine non-identical minimal patch, consistent with the reported +427 bytes.

## Step 9: Complete PRD — 2026-09-04T18:36:45.372Z

Step 9 always runs. The orchestrator split it into **three sequential module-partitioned passes** over one shared `workspace/PRD_COMPLETED.md` (pass 1 owns the `cp` from `PRD_FINALIZED.md`; passes 2–3 edit in place). Rationale for splitting: a single subagent cannot hold 2,868 lines of implementation plus a 503-line PRD and still scan exhaustively — an unsplit Step 9 characteristically returns a byte-identical file, i.e. it never really scanned.

Partition: pass 1 = `app.py`, `errors.py`, `response.py`, `db.py`, `middleware.py`, `lookups.py`, `listing.py`, `routes/config.py`, `routes/candidates.py`. Pass 2 = `calculations.py`, `services.py`, `routes/book.py`, `routes/conflicts.py`. Pass 3 = `cascades.py`, `routes/offers.py`, `routes/integration.py`. Each pass handed its out-of-partition observations forward to the next pass rather than patching them.

### Totals
- `PRD_FINALIZED.md` 503 lines / 111,700 chars → `PRD_COMPLETED.md` 504 lines / 126,142 chars (**+14,442 chars, +12.9%**; +1 line from a single added §2.2 bullet).
- **64 changes total: 49 ambiguity-pins, 15 mismatch-revisions.** Per pass: pass 1 = 17 pins + 2 mismatches; pass 2 = 13 pins + 5 mismatches; pass 3 = 19 pins + 8 mismatches.

### Pass 1 (infra, config, candidates) — 17 pins, 2 mismatches
- §2.1 — insert — ambiguity — empty header value treated as absent; role name matched exactly, case-sensitive — `middleware.py:30`
- §2.2 — insert — ambiguity — `api_request_id` is `req_` + exactly 20 chars from `A-Z0-9` — `response.py:12`
- §2.2 — insert — ambiguity — new bullet: unknown route → `ERR_INVALID_REQUEST`/404, undeclared method → 405, internal failure → 500; trailing slash insignificant — `app.py:23,55-80`
- §2.3 — insert — ambiguity — `created_at` ties broken by creation sequence (the logical clock makes ties the norm) — `db.py:84-90`
- §2.3 — insert — ambiguity — practice groups filterable by `status`; search firms accept no filter — `config.py:64,123`
- §2.3 — insert — ambiguity — filters are unvalidated exact string matches (bogus enum/FK → empty page, not an error); unlisted query params ignored; `include_withdrawn` accepts `true/1/yes` vs `false/0/no` case-insensitively — `listing.py:18-24`, `middleware.py:216-225`
- §2.4 — insert — ambiguity — a write leaving every field unchanged bumps neither `updated_at` nor `version`; a multi-field write bumps once — `db.py:72-81`
- §2.4 — insert — ambiguity — clock written before any sweep, backwards moves accepted, response 200 with empty `data` — `config.py:230-236`
- §2.5 — insert — ambiguity — money/ratio/integer fields travel as JSON numbers both ways; quoted-string or boolean input → `ERR_INVALID_REQUEST` — `middleware.py:116-142`, `db.py:93-102`
- §2.10 item 4 — insert — ambiguity — empty/absent body read as `{}`; non-object or unparseable body → 400; undeclared body fields ignored; zoneless ISO instants read as UTC, offsets normalised; no-input endpoints never parse the body — `middleware.py:37-50,145-157`
- §3.1 — insert — ambiguity — duplicate practice-group `name` → `ERR_INVALID_REQUEST` (400), tested after all other fields — `config.py:35-38`
- §3.1 — insert — ambiguity — freeze of a non-`OPEN` group and unfreeze of a non-`HIRING_FROZEN` group both → `ERR_PRACTICE_GROUP_FROZEN`; freeze validates `reason` first — `config.py:73-85`
- §3.1 — insert — ambiguity — duplicate search-firm `name` → `ERR_INVALID_REQUEST`, also tested last — `config.py:100-103`
- §3.2 — insert — ambiguity — approach outside the exclusivity window → `ERR_ENGAGEMENT_INVALID_STATE`; takes no payload; candidate `pipeline_status` tested before engagement — `candidates.py:89-97`
- §3.3 — insert — ambiguity — outstanding questionnaire → `ERR_QUESTIONNAIRE_INVALID_STATE`; previously unstated guard: sourcing engagement must be `ACTIVE` at issue → `ERR_ENGAGEMENT_INVALID_STATE`; guard order pinned — `candidates.py:130-137`
- §3.3 — insert — ambiguity — `primary_matter_types` carries no distinctness requirement (unlike entry `matter_types`) — `candidates.py:125`
- §3.3 — **revise** — **mismatch** — `entry_count` is refreshed *before* the floor of 1 is tested (PRD said on success); engagement test precedes the empty-book test — `candidates.py:184-187`
- §3.3 — insert — ambiguity — questionnaire `accept` takes no payload; no `CURRENT` assessment → `ERR_QUESTIONNAIRE_INVALID_STATE` — `candidates.py:220-227`
- §4 intro — **revise** — **mismatch** — ownership check applies only to the nine §2.10 priority-6 write endpoints; no read/list endpoint checks ownership — `candidates.py:70-71,157-158`

Verified clean by pass 1: `errors.py` ERROR_STATUS vs the §5 table (62 codes, identical set/statuses/order); all role lists match the §4 table exactly; engagement geometry (half-open exclusivity + quiet gap, closed-interval capacity), check ordering 17→18→20→22, and `engagement_count` recount-across-all-statuses were already pinned.

### Pass 2 (calculations, services, book, conflicts) — 13 pins, 5 mismatches
- §2.3 — revise — mismatch — added the two filters the impl accepts but the PRD's exhaustive list omitted (`portable_status` on book entries, `governing_basis` on assessments) — `routes/book.py:81,215`
- §2.8 — revise — mismatch — "maintained incrementally as offers move" replaced by a rebuild-from-definitions statement (all three figures recomputed from status-restricted sums on every offer movement, `available` derived), keeping §3.6's per-transition deltas as the guaranteed observable — `services.py:18-35`
- §3.3 — insert — ambiguity — a `DELETE` on an already-`WITHDRAWN` entry is neither error nor mutation: 200, row unchanged, `entry_count` untouched, no assessment turned `STALE` (owner + mutability still checked first) — `routes/book.py:96-97`
- §3.4 — insert — ambiguity — `client_book_entry_id` read only when it arrives as a string; any other JSON type treated as omission and written as a null reference — `routes/book.py:112-113`
- §3.4 — insert — ambiguity — a supplied entry is accepted whatever its own `status` (`WITHDRAWN` included) and whatever candidate's questionnaire it hangs from — `routes/book.py:112-113,133-136`
- §3.4 — insert — ambiguity — `lookback_start_date` preserves month and day except a 29 February `baseline_date`, which moves back to 28 February — `services.py:131-135`
- §3.4 — insert — ambiguity — an already-`DECLINED` entry keeps that status through a fresh valuation while its `baseline_portable_amount_usd` is still rewritten — `services.py:157-165`
- §3.4 — insert — ambiguity — the staleness recomputation touches only the three totals; `entry_count_in_scope`, `self_reported_total_usd`, `variance_pct`, both concentration shares, the grade and the haircut stay frozen, so a `SELF_REPORTED` assessment's `adjusted_portable_total_usd` does not move — `services.py:214-235`
- §3.5 — insert — ambiguity — `affected_matter_types` items are 1–60 chars with no distinctness requirement — `routes/conflicts.py:26`
- §3.5 — insert — ambiguity — the entry-`ACTIVE` test runs before the questionnaire-status test and both report `ERR_QUESTIONNAIRE_INVALID_STATE` (the catalogue has no entry invalid-state code) — `routes/conflicts.py:31-35`
- §3.5 — revise ×4 — ambiguity — clear-check / waiver-grant / waiver-refuse `resolution_note` and `rescission_note` all pinned as required, 1–500 chars — `routes/conflicts.py:76,143,167,197`
- §3.5 — insert — ambiguity — the rescission recomputation moves no assessment `status` (a `STALE` one stays `STALE`) and never returns an offer out of `REPRICE_REQUIRED` — `routes/conflicts.py:217-219`
- §3.6 — revise — mismatch — "All seven computed economics fields … and the derived fee figures" corrected to the six fields the offer actually carries, plus an explicit statement that the offer has no fee-basis field (basis lives only on the engagement) — `services.py:283-314`, `routes/offers.py:70-82`
- §3.6 — revise — mismatch — the terminated-engagement sentence rewritten: `TERMINATED` short-circuits ahead of the calendar to `NONE`/`0.00` even inside the exclusivity window (the old justification "its terms zeroed" is false — `fee_pct` survives termination), and `EXPIRED` is explicitly not short-circuited — `services.py:263-280`
- §3.6 — revise — mismatch — "regardless of that engagement's current `status`" qualified with the single `TERMINATED` exception — `services.py:266-267`
- §3.6 — insert — ambiguity — quorum minimum pinned as an exact ceiling: a whole product stands unchanged, so a roll of five needs three votes not four — `calculations.py:149-152`

Pass 2's adjudication of pass 1's two handoffs: (1) the rejected-submit `entry_count` refresh is **not** a real exposure — `entry_count` is written only by `sync_questionnaire_entry_count` on every entry create/soft-delete and entry `status` is written nowhere else, so at submit the refresh is always a no-op, and pass 1's own §2.4 no-op rule already covers the version bump; a global "a rejected request writes nothing" rule would have been *wrong*, since `create_assessment` does mutate entries via `value_entries` before later failure points. (2) The whole-ledger recompute was revised as wording only — no observable divergence was constructible, but the old sentence pinned a mechanism the impl does not use. §3.6's delta prose and §3.7's `active_onboarding_count` prose were deliberately left alone (observationally exact).

### Pass 3 (cascades, offers, integration) — 19 pins, 8 mismatches
Mismatch revisions:
- §2.3 — "none of these filters is validated" was false for the one integer filter; `round_number` on the vote listing is integer-parsed and a non-integer is `ERR_INVALID_REQUEST` — `routes/offers.py:292`
- §3.2 hop 2 — **every** offer of that candidate lapses, not just the one `open_offer_id` names — `cascades.py:50-54`
- §3.5 hop 3 — an entry declines from `UNVALIDATED` as well as `VALIDATED` (baseline `0.00`, all shares `0.00`), and one declination set is written **per blocked check**, so a second blocking check on the same entry writes a second full set — `cascades.py:78-91`
- §3.5 split invariant — the exact-sum invariant now reads "for one entry **by one blocked check**" — `cascades.py:80-91`
- §3.6 submit — the five guards fire in §3.6's stated order, so `ERR_COMMITTEE_TOO_SMALL` beats `ERR_PRACTICE_GROUP_FROZEN` even though §2.10 ranks the group check earlier — `routes/offers.py:141-145`
- §3.6 voting — `rationale` is 1–500 chars, an empty string rejected (was "up to 500") — `routes/offers.py:251`
- §3.6 countering — the "identical side-effect set" claim was wrong for the `REPRICE_REQUIRED` edge; only a counter out of `COMMITTEE_REVIEW` releases, and the vote clause is a no-op from `REPRICE_REQUIRED` — `routes/offers.py:193-206`
- §4 endpoint table — the `counter` row now reads "Chair sends the offer back for repricing ({COMMITTEE_REVIEW, REPRICE_REQUIRED} -> COUNTER_REQUESTED)", replacing "Candidate counters an approved offer (APPROVED -> COUNTER_REQUESTED)" — `routes/offers.py:187-196`. This resolves the PRD's internal §4-vs-§3.6 inconsistency that both the test generator and pass 2 flagged.

Ambiguity pins: sweep order engagements → waivers → plans, with the waiver sweep noted as the only one with downstream reach (`cascades.py:116-143`); both pinned-version fields integer-only so a zero/negative value yields 412 not 400 (`routes/offers.py:49`, `routes/book.py:171`); body FKs resolved only when they arrive as JSON strings (`routes/offers.py:43-46`, `routes/integration.py:31-36`); the no-body endpoint list made exhaustive (`routes/offers.py:155,209`, `routes/integration.py:108,208`); an expired waiver's `resolution_note` stays null (`cascades.py:101-106`); `accepted_at` starts null (`routes/offers.py:81`); offer creation overwrites `open_offer_id` whatever it held and leaves earlier offers untouched (`routes/offers.py:85`); the re-draft probe hire instant is the clock at re-draft time (`routes/offers.py:120`, `services.py:296`); `eligible_voter_count` integer ≥ 0 so a negative roll is a 400 (`routes/offers.py:131`); submit performs no candidate `pipeline_status` test, so a second `DRAFTED` offer on an `OFFER_OUT` candidate can still submit and reserve (`routes/offers.py:133-147`); the roll is never null in `COMMITTEE_REVIEW`, so neither the roll-full test nor the quorum denominator meets a null roll (`routes/offers.py:263-265,170`); an all-abstain round satisfies the whole-number two-thirds test and approves (`routes/offers.py:174`, `calculations.py:156`); neither finalize branch tests `pipeline_status` (`routes/offers.py:175-182`); `counter_note` 1–500 (`routes/offers.py:192`); acceptance hop 2 rewrites `open_offer_id` and hop 3 sets `FEE_DUE` unconditionally, overwriting a terminated engagement's `FEE_WAIVED` with basis `NONE`/`0.00` (`routes/offers.py:227-238`); plan create performs no duplicate-plan test so several plans may coexist (`routes/integration.py:61-73`); `abandonment_reason` 1–500 (`routes/integration.py:99`); introduction candidate-`HIRED` failure is `ERR_CANDIDATE_INVALID_STATE`, tested after the plan's `ACTIVE` requirement (`routes/integration.py:144-148`); completing before `slot_start_at` is `ERR_INTRODUCTION_INVALID_STATE` (`routes/integration.py:217-219`); review candidate-`HIRED` code, guard order, and that the named plan need not belong to the path candidate and its `status` is never examined (`routes/integration.py:244-249`).

Pass 3's adjudications: the null-roll branches (`offers.py:263-265`, `:170`) are provably unreachable, so instead of documenting dead branches it pinned the invariant that makes them dead. `cascades.py:58-62` hop 3/4 plan abandonment is also unreachable (a plan can only name an `ACCEPTED` offer, `ACCEPTED` never lapses, a `HIRED` candidate cannot be withdrawn) — deliberately **no change**, since §3.6 line 328 and §3.2 hop 3 already gate the prose to `COMMITTEE_REVIEW`/`APPROVED`. Sweep order is state-invariant (engagement expiry touches nothing the later sweeps read; plan completion touches nothing the waiver cascade reads), so only the order plus the waiver sweep's reach was asserted.

### Completeness statement (pass 3)
Every endpoint, transition, guard, ordering, cascade hop, sweep, counter and computed field in `implementation/` traces to a sentence in `PRD_COMPLETED.md`. Knowingly left unpinned: deep-defensive `None` branches (`cascades.py:74`, `routes/offers.py:139,255`, `integration.py:29-34,260`, `services.py:265`) unreachable given creation-time referential integrity; `create_introduction`'s confidential-approach scan iterating every questionnaire of the candidate regardless of status (`integration.py:157`), indistinguishable from existing §3.7 wording because a candidate can only ever hold one questionnaire; and intra-priority-7 ordering in `create_plan` (`integration.py:49-52`), already implied by §2.10's "path order, then body order".

### Orchestrator verification
- `PRD_COMPLETED.md` is **not** byte-identical to `PRD_FINALIZED.md` — `diff` reports 48 changed lines and +14,442 chars, so the scan demonstrably ran (the characteristic unsplit-Step-9 failure mode is an identical file).
- The file is 504 lines and still ends on `| ERR_GUARANTEE_BUDGET_EXCEEDED | 402 |` — no truncation across three passes of surgical edits.
- `find` over `workspace/implementation/`, `test_suite/`, `test_helpers/` for files modified after the 17:53 sweep returns nothing: Step 9 touched documentation only, so the verified 8×117/117 green sweep still describes the shipped artifacts.
- Only one `worklog.md` exists (task root); no `workspace/`-nested worklog or stray test dirs.

**PIPELINE COMPLETE.**
