# Worklog — task_2222_vehicle_safety_recall_campaign_execution

## Step 1: Create task directory — 2026-09-01T05:43:09.646Z

Created `tasks/task_2222_vehicle_safety_recall_campaign_execution/` and `tasks/task_2222_vehicle_safety_recall_campaign_execution/workspace/`.

## Step 2: Generate scaffold — 2026-09-01T07:26:00.000Z

Final linter run (verbatim):

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           tasks/task_2222_vehicle_safety_recall_campaign_execution/SCAFFOLD.yaml
  Difficulty design:  tasks/task_2222_vehicle_safety_recall_campaign_execution/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      tasks/task_2222_vehicle_safety_recall_campaign_execution/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    49
  §1.1 entities declared:     13
  §1.8 instances scanned:     18
  §1.9 instances scanned:     81
  Calls scanned (§1.8+§1.9):  1076

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## Generated artifacts

All under `/home/ubuntu/github/CodingPRD/tasks/task_2222_vehicle_safety_recall_campaign_execution/`:

**SCAFFOLD.yaml** (§1.0–§1.7, no design keys) — 13 entities, 7 state machines, 2 OCC concurrency rules, 12 calculations, 46 ordered validations, 49 endpoints, 50 error codes, 5 roles. Profile: `compliance_audit` × `quota_allocation`, branching state machine, `segregation_of_duties`, `immediate` consistency, `difficulty_level: expert_plus`.

**SCAFFOLD_DIFFICULTY_DESIGN.yaml** (§1.8) — 9 rule_ids × 2 instances = 18, covering non-linear state machine, compensating invariant, transitive cascade, half-open interval comparison, waterfall/quota allocation, dual-variant rates, threshold-triggered revision, OCC, and priority-ordering conflicts.

**SCAFFOLD_CORNER_DESIGN.yaml** (§1.9) — 95 instances across all 9 legal sections: 81 full `test_recipe` instances + 14 `excluded_because` stubs (entities 12, state_machines 20, calculations 17, validations 16, endpoints 6, errors 12, rbac 5, cross_cutting_layers 6, consistency_model 1).

## Coverage checks (independent audit)

- Every `claim_type` row from `references/claim-extraction-guide.md` is represented in its section, including the last gap I closed this run (`interval_merge` in calculations, filed as a stub citing `population_rule_half_open_window_allows_touch_rejects_intersection`).
- All 50 declared error ids are triggered somewhere in §1.8 ∪ §1.9; zero references to undeclared codes.
- Instance names unique across the union of both design files; every stub cites a bare instance name that exists in §1.8 and carries no `test_recipe`; every full instance has all four recipe keys plus `claim_type` and non-empty `grounds`.

## Design notes worth flagging for the PRD/test author

- Hardest layers are the wave-release quota pipeline (6 pinned steps: severity-gated `provisional_coverage_ratio` → tier factor 1.00/0.75/0.40/0.00 → `floor` planned count → reported `parts_coverage_ratio`) and the dual completion-rate variants (`regulatory` excludes only removed vehicles; `operational` also excludes unreachable and credits scheduled).
- `remedy_effectiveness_score` revision trigger is deliberately strict (`< 70.00`); a corner case pins a score of exactly 70.00 with no revision.
- Owner reimbursement and dealer claim reimbursement use separate rate sources (prevailing 115.00 vs `RATE_CAP_BY_REGION`), which is the main variant-selection trap.
- Validation-precedence traps depend on the ordered list (e.g. priority 11 before 21/22/25; 34 before 44; 37 before 44), so implementations that reorder checks will fail those cases.
- No report/summary markdown files were written.

## Step 3: Copy shared files — 2026-09-01T07:27:06.890Z

Copied `INSTRUCTION.md` to `tasks/task_2222_vehicle_safety_recall_campaign_execution/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-01T07:41:25.334Z

PRD generated and verified at `/home/ubuntu/github/CodingPRD/tasks/task_2222_vehicle_safety_recall_campaign_execution/workspace/PRD.md` (393 lines). The two withheld design files were never opened, and no sibling task directory was read.

## Structure

- **§1 Introduction** — 3 paragraphs; frames the four competing pressures (statutory deadline, unfinished remedy, finite kit pool, quarterly completion reporting) and names the two cross-cutting commitments (conservation, segregation of duties).
- **§2 Global Specifications** — 11 subsections: 2.1 RBAC (all 5 roles, `identity` semantics translated explicitly, `entity_backed:Dealer` for `DealerServiceManager`), 2.2 API Response Structure (verbatim from `section-2.2-response-structure.md`), 2.3 Pagination, 2.4 Record Identity/Timestamps/Logical Clock (`2026-08-01T00:00:00Z` default; `OutreachAttempt` exception to `updated_at`/`version`), 2.5 Two Independent Campaign Dimensions + Cascades A and B link-by-link, 2.6 Segregation of Duties, 2.7 Nested Paths and the 13-band Validation Precedence chain, 2.8 Version Guards, 2.9 Parts Conservation, 2.10 Obligation Ledger Conservation, 2.11 Numeric Precision (pinned rounding order).
- **§3 Business Logic** — 9 subsections: 3.1 determination/deadline/supersession, 3.2 population build from build records, 3.3 regulatory filings, 3.4 remedy engineering incl. forced revision, 3.5 parts/labor/allocation grant, 3.6 notification waves with the 6 pinned quota steps, 3.7 dealer repair claims and audit/reversal, 3.8 outreach and auto-scheduled follow-up waves, 3.9 completion reporting, owner reimbursement and closure.
- **§4 Endpoint Definitions** — 49 rows, 4 columns.
- **§5 Error Code Catalogue** — 50 rows, 2 columns. Document ends at §5 with no audit footer.

## Coverage audit

```
Field coverage check:
- entities[].fields: 130 required, 130 present, 0 missing
- endpoints[].request_body: 79 required, 79 present, 0 missing
- endpoints[].query_params: 23 required, 23 present, 0 missing
- non-entity response-shape names: 16 required, 16 present, 0 missing
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: 46 checked, 46 expressed in prose, 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write_endpoint + expected_<parent>_version + error_id all named), 0 missing
- state_machines[].transitions: 36 checked (7 machines incl. both RecallCampaign dimensions), 36 fully expressed, 0 missing
- calculations[]: 12 checked, 12 fully expressed, 0 missing
- validations[] conditions: 46 checked, 46 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 28 endpoints with side effects checked, 28 expressed, 0 missing
- entities[].fields[] structured content: 13 entities checked, 13 reconstructible from prose, 0 missing
- sibling-branch symmetry: 6 groups checked (INCLUDE/EXCLUDE rules; INTERIM/REMEDY/FOLLOW_UP wave candidate filters; PROVISIONAL/FINAL claim amounts; REGULATORY/OPERATIONAL completion; APPROVE/REJECT claim audit; APPROVE/DENY reimbursement adjudication), 6 with equal prose density, 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 933
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

## Key verifications

- All 50 error IDs and their HTTP statuses match the scaffold exactly (0 missing, 0 extra, 0 status mismatches).
- All 49 endpoint method+path pairs match, and every role list matches (5-role rows rendered as "All roles").
- All 13 `201`-returning creates are enumerated in the §4 preamble; the other 36 return `200`.
- Calculation constants are carried as natural-language equivalents where the skill forbids pseudocode (`0.15` as "fifteen percent … one plus fifteen hundredths", `1.5` as "one and a half times", `14` as "fourteen whole days"); every other constant appears as a literal.
- Deliberately preserved distinctions the implementer must not conflate: half-open production window vs. closed part-number and labor-effectivity windows; `provisional_coverage_ratio` (gate input, eligible-count denominator) vs. `parts_coverage_ratio` (reported, planned-count denominator); regulatory vs. operational completion denominators; stored vs. recomputed `final_amount_cents` on reversal.

## Step 5: Generate unit tests — 2026-09-01T09:06:51.702Z

All three remaining queue-B files are written, and both mandatory audit passes are clean.

## Files written

**Stage 1 — `test_helpers/`** (9 modules, completed earlier): `__init__.py` (barrel, 97 exports), `api_client.py`, `api_errors.py`, `assertions.py`, `constants.py`, `factories.py`, `fixtures.py`, `test_users.py`, `types.py`.

**Stage 2 — `test_suite/`** (16 modules + `conftest.py`), **117 tests total**:

| file | tests |
|---|---|
| test_01_difficulty_population.py | 4 |
| test_02_difficulty_remedy_engineering.py | 4 |
| test_03_difficulty_notification_waves.py | 6 |
| test_04_difficulty_repair_claims.py | 8 |
| test_05_difficulty_claim_audit_and_reversal.py | 8 |
| test_06_difficulty_filings_and_metrics.py | 4 |
| test_07_difficulty_owner_reimbursement.py | 2 |
| test_20_corner_entities.py | 12 |
| test_21_corner_state_machines.py | 17 |
| test_22_corner_calculations.py | 11 |
| test_23_corner_validations.py | 14 |
| test_24_corner_endpoints.py | 5 |
| test_25_corner_errors.py | 12 |
| **test_26_corner_rbac.py** (new) | 5 |
| **test_27_corner_cross_cutting.py** (new) | 4 |
| **test_28_corner_consistency.py** (new) | 1 |

## Counts per queue

- **Queue A (Difficulty, §1.8):** 18 instances, 0 stubs → **36 tests**, exactly 2 per instance, no instance over- or under-covered.
- **Queue B (Corner, §1.9):** 95 instances, 14 `excluded_because` stubs → 81 non-stub → **81 tests**, ≥1 per instance, every non-stub instance covered.
- Every test carries exactly one `Design:` line; 117 tests / 117 tags, no untagged, no dual-tagged, no tag pointing at a missing instance, no stub translated.

## Audit passes

- **PRD-citation pass:** all 208 quoted sentences are byte-verbatim substrings of `workspace/PRD.md` after whitespace reflow, and every `PRD §x.y` label resolves to the section that actually contains the quote. This pass found 9 quotes in the queue-A files that had silently dropped markdown emphasis (`**half-open**`, `rounded **down**`, `*do* intersect`, `the **stored** final_amount_cents`, etc.); I restored the markers so a literal grep survives. Docstrings only — no assertion changed.
- **Scaffold-citation pass:** all 14 stub `excluded_because.difficulty_instance` cross-references resolve to real difficulty instances (verified, nothing emitted for them).
- All 16 modules import cleanly; no unused imports; no occurrence of "scaffold", scaffold section refs, or `implementation/` anywhere in generated code.

## Instances skipped

- **0 instances skipped for the PRD-first two-condition filter** — every non-stub instance had verbatim PRD coverage and a uniquely derivable outcome.
- **14 corner instances not translated because they are `excluded_because` stubs** (state_machines 3, calculations 6, validations 2, endpoints 1, cross_cutting_layers 2), each deferring to a queue-A difficulty instance that already drives the same chain.

## Design-vs-PRD conflicts I had to reconcile (asserted numbers kept, setup corrected)

Four corner recipes assert allocation quantities their own setup cannot produce under PRD §3.5's regional-demand cap (`min(requested_qty, monthly_repair_capacity, unrepaired/scheduled rows in the dealer's region)`):

- `endpoints/allocation_links_a_part_and_a_dealer…` (26V-329) and `rbac/recall_operations_manager_performs…` (26V-337) — setups create no matched population yet assert 3 and 2 granted; I seeded 3 and 2 matched NE rows so the asserted numbers are PRD-correct.
- `cross_cutting_layers/parts_allocation_with_a_stale_part_version…` (26V-343) — asserts a 10-unit grant and `unallocated_qty == 90` with no population; seeded 10 matched NE builds.
- `cross_cutting_layers/effectiveness_score_exactly_at_the_minimum…` (26V-345) — a 4-unit allocation is impossible against 3 eligible rows, so the test allocates 3, consumes all 3 on the three approved claims, then re-allocates the "one remaining unit" the recipe's own prose describes (a supersede, per §3.5), which is what makes the REMEDY wave clear the LOW 0.3000 coverage gate. All asserted figures (70.00 score, 66.67 completion, remedied 2, population 3, revision count 0) are unchanged.

One further correction: `rbac/defect_notice_filed_by_the_determining_user_is_rejected` asserts `days_late` is null after the refusal; PRD §3.1 says a new campaign starts with `days_late` 0, so the test asserts 0.

## Step 6: Generate implementation — 2026-09-01T09:06:51.702Z

Implementation complete and verified.

## Files written
All under `/home/ubuntu/github/CodingPRD/tasks/task_2222_vehicle_safety_recall_campaign_execution/workspace/implementation/` (3,106 lines total):

- `start.sh` (executable; `exec python3 app.py`, pip install only when Flask is missing so per-test reboots stay fast — measured ~0.6 s to first served request), `requirements.txt` (`Flask==3.0.3`)
- `app.py` — blueprint registration, `before_request` per-request touch set, `ApiError`/`HTTPException`/catch-all handlers emitting the error envelope, binds `0.0.0.0:$PORT` (default 10000)
- `db.py` — in-memory `Store` (13 dicts + logical clock pinned to `2026-08-01T00:00:00Z`), instant/date formatting and parsing, `base_record`, `touch` (version bumped at most once per record per request), ordering helpers
- `errors.py` — all 50 error ids with statuses (verified programmatically against the PRD table: exact match, no extras, no gaps)
- `response.py`, `auth.py`, `validators.py`, `calc.py` (all constants, deadline/lateness, completion rates, effectiveness score, claim and reimbursement arithmetic, wave quota, allocation pick), `helpers.py` (lookups, state gates, cascades, serializers)
- `routes/{campaigns,population,waves,parts,claims,reimbursements,filings,clock}.py` + `routes/__init__.py`

## Endpoints
**49**, exactly matching the PRD endpoint table (method + path set compared programmatically against `app.url_map` — zero diff in either direction).

## Notable design decisions
- **Derived-at-read**: every counter and rate (campaign population buckets, `completion_rate_pct`, `remedy_effectiveness_score`, `reimbursement_obligation_cents`, `open_followup_wave_count`, `approved_claim_count`, `outreach_attempt_count`, labor-op `claim_count`, rule `matched_vehicle_count`) is computed at serialization time, so §2.9 parts conservation and §2.10 money conservation hold by construction. Only genuinely pinned values are stored (wave quota fields, filing snapshots, provisional/final amounts, `is_repeat_repair`, `days_late`, pool counters).
- **`touch()` bumps `version` at most once per record per request**, satisfying "increments the campaign's version once, not twice" and making the allocation endpoint bump the part version exactly once despite two pool movements.
- **Remedy availability** is uniformly `remedy_status ∉ {REMEDY_UNDER_DEVELOPMENT, INTERIM_ONLY}` (matches the error-catalogue condition) for wave release, scheduling, claim submission and claim approval. Releasing a remedy from `REMEDY_RELEASED` is refused with `ERR_REMEDY_ALREADY_AVAILABLE` (the scaffold enumerates only the three other inbound states; both candidate ids are 409).
- **Filing duplicates**: `ERR_FILING_PERIOD_DUPLICATE` covers one `DEFECT_NOTICE` per campaign and `report_period` uniqueness across filings; `AMENDMENT` is exempt and instead falls through to `ERR_NO_QUARTERLY_FILING_TO_AMEND` (otherwise no amendment could ever be filed). Snapshots are frozen *after* lateness is settled, so a late defect notice snapshots 95.00.
- **Reimbursement re-check at adjudication applies to APPROVE only** (a denial must stay possible), and `documentation_complete == false` on approve → `ERR_REIMBURSEMENT_INVALID_STATE`.
- The campaign-terminal write gate applies to campaign-scoped creates/transitions but deliberately not to compensating actions (wave cancel, allocation revoke, claim audit/reverse, reimbursement adjudicate/documents/resubmit).
- `dealer_code` uniqueness is not enforced (no error id exists for it); enum query filters validate to `ERR_INVALID_REQUEST`; instants always emit exactly 3 fractional digits + `Z`.

## Verification
Three smoke suites run against freshly booted servers, all green apart from four expectations in my own scripts that were wrong (I confirmed each against the PRD and left the implementation as-is): full happy path through closure; cascade A (reversal → ledger unwind → unit return → auto `FOLLOW_UP` wave at clock+21 d, one per region); cascade B (score 40.00 < 70.00 → `REMEDY_REVISED`, rows reset with `requires_renotification`, allocations revoked `REMEDY_REVISED`, `amendment_required` true, then amendment flips the quarterly to `AMENDED`); OCC 412s; SoD 403 preceding state gates; band-precedence spot checks; arithmetic checks (claim 175.50 with the NE rate cap, 427.00 provisional, reimbursement cap 370.00, filing deadline `2026-08-10T23:59:59.000Z`, `days_late` 1 for 30 s past the deadline). Store is empty on every boot; no file, SQLite or JSON persistence anywhere in the tree.

## Step 7: Run tests and iterate — 2026-09-01T09:19:52.804Z

All 8 parallel rounds now pass 117/117 with zero failures, errors, or skips.

## Summary

**Iterations run:** 2 (each iteration = one full 8-round parallel stability sweep)

- **Sweep #1:** all 8 rounds 108/117 — perfectly stable signal, 9 unique failing tests, no flakiness, collapsing to 3 root causes.
- **Sweep #2** (after fixes): all 8 rounds **117/117**, union of failures across all rounds = **0**.

**Tests deleted:** none. Every failing test survived STEP 1a (PRD verbatim coverage) and STEP 1b (unique derivability); no test asserted a scaffold-only or PRD-silent rule.

**Fixes applied to `test_helpers/`:** none. Triage showed the fixture/factory layer was consistent with PRD throughout.

**Fixes applied to `test_suite/`** (STEP 2 — test was wrong, made *more* faithful to PRD):
- `test_suite/test_22_corner_calculations.py` (lines 199, 255) and `test_suite/test_28_corner_consistency.py` (line 41) — `validate_success(api.run_population(...), 200)` → `201`. PRD §4 verbatim lists "a population run" among the operations that "return `201 Created`", so the assertions were mis-translations; the implementation was already correct.

**Fixes applied to `implementation/`** (STEP 3 — test faithful, PRD covers and uniquely determines):
- `workspace/implementation/calc.py` — new `fmt_deadline()`: renders `filing_deadline_utc` with no fractional seconds, per PRD §3.1 "`filing_deadline_utc` is that fifth counted date pinned to 23:59:59Z" (this field is not in §2.4's list of three-fractional-digit server-stamped instants).
- `workspace/implementation/routes/campaigns.py` — `defect_determination()` now uses `calc.fmt_deadline(...)`; `create_campaign()` persists `remedy_effectiveness_score = Decimal("100.00")` per PRD §3.1; `close_campaign()` and `completion_metrics()` read the stored score instead of recomputing live.
- `workspace/implementation/helpers.py` — new `recompute_effectiveness()`; `campaign_out()` serializes the stored score. PRD §3.9 names exactly three recompute events, so the score is a persisted field, not a live derivation.
- `workspace/implementation/routes/claims.py` — `audit_claim()` (approval branch) and `reverse_claim()` call `recompute_effectiveness()`, per PRD §3.9 "recomputed on every repair-claim approval, on every repair-claim reversal".
- `workspace/implementation/routes/filings.py` — recompute before `_snapshot` for QUARTERLY and AMENDMENT only (PRD §3.9 does not list the defect notice); `_snapshot` freezes the persisted score into `effectiveness_score_snapshot`.

**Key finding:** the third root cause was subtle and only surfaced through Cascade B. Because `campaign_out` computed the score live, reverting the only `REMEDIED` row during the remedy-revision cascade collapsed the repeat-repair rate to 0 and the score re-read as 100.00 instead of the 40.00 frozen at filing time. Persisting the field per PRD §3.1/§3.9 fixed both the cascade test and kept all eight other score/snapshot assertions in the suite satisfied (verified by cross-checking test_06, test_20, test_22, test_23, test_24, test_27 before committing to the refactor).

Storage remains in-memory only (Python dicts in `db.Store`, empty on every boot); no seeding, no file/SQLite/`/tmp` persistence.

**Orchestrator re-verification:** the orchestrator independently re-ran the full 8-round parallel sweep after the subagent exited (the subagent had deleted its result files). Result: rounds 1–8 all `117 / 117`. `results.{1..8}.json` are on disk from this sweep.

## Step 8: Finalize PRD — 2026-09-01T09:24:10.614Z

Done. `PRD_FINALIZED.md` written with two surgical edits.

## Line counts
- `PRD.md`: 393 lines; `PRD_FINALIZED.md`: 393 lines — **0.00% line-count delta** (2 lines revised in place, no lines added or removed).

## Changes
- **§3.1 (filing deadline)** — *revise* — appended the exact rendering of `filing_deadline_utc`: whole seconds, `YYYY-MM-DDT23:59:59Z`, no fractional-second digits — `implementation/calc.py:147-153` (`fmt_deadline`), used at `implementation/routes/campaigns.py:109`.
- **§3.9 (effectiveness)** — *revise* — appended that `remedy_effectiveness_score` is a **persisted** campaign field (not derived at read time), set to 100.00 at campaign creation, changed only at the recompute events already listed; that campaign reads, completion-metrics, the closure gate and filing snapshots all report the last-stored value; and that inside a filing the recompute runs once immediately before the snapshot freeze — so a defect notice freezes the score as it stands and the revision cascade does not refresh it — `implementation/routes/campaigns.py:66,211,243`, `implementation/helpers.py:96-98,245`, `implementation/routes/claims.py:168,211`, `implementation/routes/filings.py:21,96-97,105-106`.

## Per-edit pre-edit search log

**Edit 1 — §3.1 deadline rendering**
- (a) Subject: serialization format of `filing_deadline_utc`, and whether the claim leaks onto other instants.
- (b) Enumerated/read: `grep -rn "fmt_deadline\|filing_deadline"` → `calc.py:137` (`filing_deadline`), `calc.py:147` (`fmt_deadline`, the only no-fraction formatter, single callsite `routes/campaigns.py:109`), `routes/campaigns.py:51` (initial `None`), `routes/filings.py:84-85` (parsed back via `parse_instant`, which tolerates a missing fraction), `helpers.py:230` (pass-through in `campaign_out`). Also `grep -rn "fmt_instant"` to confirm every *other* instant (`filed_at`, `remedy_released_at`, `defect_determination_date`, `last_notice_date`, `actual_mail_date`, `attempted_at`, `created_at`/`updated_at`, clock `current_utc`) still goes through `db.py:44` three-fractional-digit formatting.
- (c) Adjustment: scoped the sentence strictly to `filing_deadline_utc` (no general statement about "deadlines" or "server-stamped instants"), so §2.4's three-digit convention for every other instant is untouched.

**Edit 2 — §3.9 score persistence**
- (a) Subject: every read, write and freeze of `remedy_effectiveness_score` / `effectiveness_score_snapshot`.
- (b) Enumerated/read: `grep -rn "remedy_effectiveness_score\|recompute_effectiveness\|effectiveness_score_snapshot\|REMEDY_EFFECTIVENESS_MIN"` → writes at `routes/campaigns.py:66` (creation 100.00), `helpers.py:98` (only mutator), called from `routes/claims.py:168` (approval only — the REJECT branch returns at `claims.py:136-140` before it), `routes/claims.py:211` (reversal), `routes/filings.py:96` (QUARTERLY) and `:105` (AMENDMENT), with `DEFECT_NOTICE` at `:83-92` deliberately not recomputing; reads at `helpers.py:245` (`campaign_out`), `routes/campaigns.py:211` (closure gate), `:243` (completion-metrics), `routes/filings.py:21` (`_snapshot`, all three filing types). Also confirmed the *absence* of recompute on every other campaign-mutating path: `routes/reimbursements.py`, `routes/population.py` (population runs, vehicle PATCH → `REMOVED_FROM_POPULATION`, outreach → `UNREACHABLE`), `routes/waves.py`, `routes/parts.py`, `routes/clock.py` (grep returned nothing), and inside `helpers.cascade_remedy_revision` (`helpers.py:173-185`, which changes `REMEDIED` rows but never the score).
- (c) Adjustments: (1) wrote "changes only at those recompute events" rather than enumerating a fresh list, so the existing verbatim three-event sentence stays the single source and the silent paths (population run, vehicle removal, outreach, reimbursement approval, wave mailing) are correctly described as leaving the stored score alone; (2) added the explicit defect-notice carve-out, since `_snapshot` runs for that filing type too and a blanket "a filing recomputes" would have mis-described `filings.py:83-92`; (3) added the "revision cascade does not refresh the stored score" clause to keep the post-Cascade-B stored value (40.00 while `remedied_count` is 0, per `test_06` lines 231/273) consistent with the persistence claim.

## Step 9: Complete PRD — 2026-09-01T09:36:01.336Z

33 in-place line revisions, no new lines, no new sections, headings identical.

## Summary

**Files:** source `workspace/PRD_FINALIZED.md` (393 lines, 85,095 chars) → `workspace/PRD_COMPLETED.md` (393 lines, 93,276 chars); **char delta +8,181**, line delta 0. All 33 changes are in-paragraph edits to existing lines.

**Counts:** 27 ambiguity-pins, 8 mismatch-revisions (35 distinct behaviors across 33 edited lines).

- §2.4 Record Identity — insert — ambiguity — `created_at`/`updated_at` stamped from wall clock (not the logical clock) and are what `created_at` orderings sort on; a record mutated repeatedly in one request has `version` incremented exactly once — `db.py:118,126`
- §2.4 Logical Clock — insert — ambiguity — client instants normalised to UTC with three fractional digits on storage; client calendar dates stored verbatim — `db.py:44`, `campaigns.py:106`
- §2.5 Two Dimensions — insert — mismatch — the blanket terminal-state write refusal enumerated: it guards forward/creating operations, but allocation revoke, wave cancel, claim audit/reversal, all three reimbursement steps and build-record update carry no campaign-state gate — `claims.py:120,175`, `reimbursements.py:116,136,167`, `waves.py:152`, `parts.py:257`
- §2.11 Numeric Precision — insert — ambiguity — over-precise currency/hour inputs are rounded half up on storage, not rejected — `validators.py:141`, `parts.py:33`
- §3.1 Opening the Recall File — insert — ambiguity — campaign counters (`affected_vehicle_count`, `recall_population_count`, `remedied_count`, `completion_rate_pct`, `reimbursement_obligation_cents`, `open_followup_wave_count`) are derived at serialisation, never stored — `helpers.py:218`
- §3.2 Build Records — insert — ambiguity — build-record `model_year`/`suspect_part_number` unbounded, codes any non-empty length; an empty PATCH is accepted and still bumps `version` — `population.py:159,199`
- §3.2 Population Rules — insert — ambiguity — part range gets no sanity check; `part_number_low` > `high` is accepted and matches nothing — `population.py:30`
- §3.2 Population Rules — insert — ambiguity — `matched_vehicle_count` counts rows in every status, `REMOVED_FROM_POPULATION` included — `calc.py:131`
- §3.2 Matching — insert — ambiguity — exclusion test precedes the already-materialised test, so `excluded_count` re-counts on every run — `population.py:102`
- §3.2 Retraction Sweep — insert — ambiguity — sweep consults `INCLUDE` rules only; a new `EXCLUDE` rule never retracts an existing row — `population.py:132`
- §3.3 Filings — insert — ambiguity — `narrative` 1–4000 chars; quarter digit must be 1–4; a defect notice stores `report_period` null even when supplied — `filings.py:30,34,33`
- §3.3 Amendments — insert — ambiguity — campaign `version` increments on an amendment; amendments gated only on non-terminal campaign and never raise `ERR_FILING_PERIOD_DUPLICATE` — `filings.py:53,108`
- §3.4 Remedy Release — insert — ambiguity — release while already `REMEDY_RELEASED` → `ERR_REMEDY_ALREADY_AVAILABLE`, evaluated *after* the version guard; release out of `REMEDY_REVISED` unrestricted by `campaign_status` — `campaigns.py:174,177`
- §3.4 Remedy Release — revise — mismatch — a labor operation belonging to another campaign yields `ERR_LABOR_OP_NOT_EFFECTIVE` (not a mismatch error), and its window is not consulted — `campaigns.py:180`
- §3.5 Dealers — revise — mismatch — `dealer_code` uniqueness is *not* server-enforced (no error code exists) — `parts.py:20`
- §3.5 Dealers — insert — ambiguity — suspension has no state gate: re-suspending succeeds and bumps `version`; no path back to `ACTIVE` — `parts.py:50`
- §3.5 Remedy Parts — insert — ambiguity — `lead_time_days` must be ≥ 0 — `parts.py:71`
- §3.5 Allocation — revise — mismatch — allocation names no campaign; `campaign_id` is denormalized from the part, so `ERR_PART_CAMPAIGN_MISMATCH` is never raised here — `parts.py:172,216`
- §3.5 Allocation — insert — ambiguity — the part's `version` increments by exactly 1 even when a prior holding is superseded in the same request — `helpers.py:117`, `parts.py:227`
- §3.5 Revoke — revise — mismatch — `revoke_note` is validated but neither persisted nor echoed — `parts.py:260`
- §3.6 Wave Planning — insert — ambiguity — planning open from any non-terminal `campaign_status`; no wave_type/remedy reconciliation at plan time — `waves.py:29`
- §3.6 Wave Release — revise — mismatch — `REMEDY`/`FOLLOW_UP` release accepts `REMEDY_REVISED` as well as `REMEDY_RELEASED`; campaign-state checks precede the wave-status gate; `INTERIM` error ids pinned (`ERR_REMEDY_NOT_AVAILABLE` vs `ERR_REMEDY_ALREADY_AVAILABLE` vs `ERR_INVALID_CAMPAIGN_STATE`) — `waves.py:62-74`
- §3.6 Wave Mailing — insert — ambiguity — the drop re-checks neither remedy dimension nor coverage arithmetic — `waves.py:121-125`
- §3.7 Appointments — revise — mismatch — booking requires `REMEDY_RELEASED` **or** `REMEDY_REVISED`; scrapped/exported build record → `ERR_VEHICLE_NOT_REPAIRABLE`, ahead of the remedy and dealer gates — `population.py:281,284`
- §3.7 Claims — insert — ambiguity — `claimed_labor_hours` must be greater than zero — `claims.py:24`
- §3.7 Claims — revise — mismatch — only the labor operation and the affected-vehicle row are campaign-compared; a dealer belongs to no campaign — `claims.py:46`
- §3.7 Claims — insert — ambiguity — the hours cap is a band-13 gate and therefore the last check, after the duplicate test and the parts reservation — `claims.py:62-67`
- §3.7 Audit — insert — ambiguity — rejection's `audit_note` is optional and stays null — `claims.py:124,138`
- §3.7 Approval — revise — mismatch — the source allocation's `version` increments too, not just the part's — `claims.py:161`
- §3.8 Outreach — insert — ambiguity — an attempt may be logged against a row in any `remedy_status` — `population.py:306-313`
- §3.8 Outreach — revise — mismatch — `BAD_ADDRESS` clears `owner_address_valid` regardless of row status, even with no transition — `population.py:331`
- §3.9 Reimbursement Intake — insert — ambiguity — `invoice_amount` > 0; `parts_amount`/`towing_amount` ≥ 0 — `reimbursements.py:50-53`
- §3.9 Eligibility — insert — ambiguity — any affected row qualifies incl. `REMOVED_FROM_POPULATION`; the 365-day lower bound is skipped while `defect_determination_date` is unset — `reimbursements.py:19-32`
- §3.9 Re-key — insert — ambiguity — supplied `documentation_complete` accepted but ignored; `requested_items` retained — `reimbursements.py:143,159`
- §3.9 Adjudication — insert — ambiguity — `denial_reason` optional; denial leaves campaign `version` alone; approve from `DOCUMENTS_REQUESTED` or with incomplete docs → `ERR_REIMBURSEMENT_INVALID_STATE`; labor op resolved as earliest by `created_at` — `reimbursements.py:171,185,190`
- §3.9 Closure — revise — mismatch — segregation-of-duties comparison precedes the `campaign_status` check — `campaigns.py:203-208`
- §4 Endpoints — insert — ambiguity — population run and completion-metrics return computed summaries; clock answers `{"current_utc": ...}` with three fractional digits — `population.py:139`, `clock.py:18`

## Pipeline complete — 2026-09-01T09:36:01.336Z

All 9 steps finished. `workspace/PRD_COMPLETED.md` exists on disk. Final test state: 8/8 parallel rounds at 117/117, `results.{1..8}.json` retained under `workspace/implementation/`.
