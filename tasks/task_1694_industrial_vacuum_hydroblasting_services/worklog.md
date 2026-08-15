# Worklog — task_1694_industrial_vacuum_hydroblasting_services

## Step 1: Create Task Directory — 2026-08-14T08:35:00.000Z

Task directory `tasks/task_1694_industrial_vacuum_hydroblasting_services/` and its `workspace/` subdirectory were pre-created and pre-assigned by the pipeline launcher. Step 1 treated as DONE per instructions; no index scan performed, no other task directory touched.

## Step 2: Generate Scaffold — 2026-08-14T09:48:00.000Z

Scaffold generation complete. All three artifacts are written and the lint verdict is clean.

## Files written
- `/home/ubuntu/github/CodingPRD/tasks/task_1694_industrial_vacuum_hydroblasting_services/SCAFFOLD.yaml` (§1.0–§1.7; no difficulty/corner keys)
- `/home/ubuntu/github/CodingPRD/tasks/task_1694_industrial_vacuum_hydroblasting_services/SCAFFOLD_DIFFICULTY_DESIGN.yaml` (single key `scaffold_difficulty_design`)
- `/home/ubuntu/github/CodingPRD/tasks/task_1694_industrial_vacuum_hydroblasting_services/SCAFFOLD_CORNER_DESIGN.yaml` (single key `scaffold_corner_design`)

## Counts
| Element | Count |
|---|---|
| Entities | 15 |
| State machine entries | 12 (Job appears twice: execution_status × safety_status parallel dims) |
| Calculations | 10 |
| Validations (ordered) | 30 |
| Endpoints | 87 |
| Error codes | 30 |
| Roles | 7 (all opaque) |
| Concurrency rules (OCC) | 2 |
| §1.8 instances | 21 (all 9 rules ≥2; rules 2/3/7 carry 3) |
| §1.9 instances | 63 (54 full + 9 `excluded_because` stubs), spanning all 9 claim-guide sections |

Lint verdict (verbatim):
```
Coverage
  §1.5 endpoints declared:    87
  §1.1 entities declared:     15
  §1.8 instances scanned:     21
  §1.9 instances scanned:     54
  Calls scanned (§1.8+§1.9):  1036

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```
Two FK-reverse-reachability violations (back-reference FKs on Site/Job → RateSchedule) were found and fixed by adding `active_rate_schedule_id?` / `pinned_rate_schedule_id?` filters to the existing list endpoints, then re-run to clean.

## Notable design decisions
- **Archetype**: pricing engine + compliance/audit; flat topology (all `/v1/<resource>` with FK filters), segregation-of-duties role model (profile/JHA approver must differ from submitter's `X-User-ID`), immediate consistency.
- **Difficulty beyond expert band**: dual-variant calcs on two domains (UNIT_RATE vs T&M invoicing; WEIGHT vs VOLUME manifest variance with different denominators/rounding orders — 1.13% vs 1.09% on identical inputs); combinatorial formulas in all three §0.5 modes (a) grace/cap/block downtime billing, (b) pinned per-line-then-sum rounding with a real 1-cent divergence (19493+19493 vs 38985), (c) volume-discount tier keyed on the pre-discount subtotal with pinned evaluation order (494700 vs 510000).
- **Rich machines**: JHA revision cycle + supersede-on-approve, Permit ACTIVE⇄SUSPENDED resume cycle, Job parallel dims with INVOICED→FIELD_COMPLETE revert cycle, Manifest RECEIVED/EXCEPTION branch on a strict `> 10.00` boundary (exactly 10.00 stays RECEIVED).
- **Cascades**: depth-3 profile-suspend chain (profile → manifests voided → facility reservation released → posture recompute FULL→AVAILABLE) and depth-2 invoice-void chain (invoice → job revert → downtime un-billed).
- **OCC**: two true create-with-supersede races only (schedule activation on `Site.version`, JHA approval on `Job.version`); a tempting third (generate-invoice) was deliberately rejected because it's a state precondition, and the unreachable `ERR_INVOICE_ALREADY_EXISTS` was removed so every error is triggerable.
- **Determinism**: logical clock endpoint with mandatory default `2026-08-01T00:00:00Z` drives downtime durations, permit windows/expiry sweep, and stale-assignment sweep; every numeric assert in both design files was precomputed by executing the formulas (all verified: 1203110, 297840, 251844, 494700, 15000/84000/99000, 385000, 378000, 76500, 118320, 8.35, etc.).

## Step 3: Copy Shared Files — 2026-08-14T09:51:00.000Z

Copied `./INSTRUCTION.md` to `tasks/task_1694_industrial_vacuum_hydroblasting_services/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-14T10:15:00.000Z

All checks pass. The PRD is complete and fully audited.

## Summary

**Output file:** `/home/ubuntu/github/CodingPRD/tasks/task_1694_industrial_vacuum_hydroblasting_services/workspace/PRD.md`
**Line count:** 350

### Section list
- §1. Introduction (2 paragraphs — business context + design commitments)
- §2. Global Specifications & System-Wide Principles
  - 2.1 User and Role-Based Access Control · 2.2 API Response Structure (verbatim block) · 2.3 Pagination · 2.4 Resource Identity and Change Tracking · 2.5 The Logical Clock and the Daily-Close Checkpoint · 2.6 Money, Measurement and Rounding Discipline · 2.7 Optimistic Concurrency Control · 2.8 Validation Order · 2.9 Disposal Capacity as a Reserved Ledger
- §3. Business Logic & Workflows (7 subsections, timeline/lifecycle hybrid grouping)
  - 3.1 Commercial Onboarding: Sites and Rate Schedules · 3.2 Job Intake, Fleet Registry and Crew Assignment · 3.3 Hazard Analysis and Permit Coordination · 3.4 Field Execution: Start Gates, Containment, Incidents and Safety Stops · 3.5 Standby Time and Downtime Billing · 3.6 Waste Characterization, Manifests and Facility Reconciliation · 3.7 Invoicing, Adjustment and Job Closure
- §4. Endpoint Definitions (status-code paragraph + 87-row, 4-column table)
- §5. Error Code Catalogue (30-row, 2-column table)

### Hard-contract audit results

**Contract 1 — Field-Name Coverage: PASS**
- entities[].fields (+common): 96 required, 96 present, 0 missing
- endpoints[].input: 70 required, 70 present, 0 missing
- endpoints[].query_params: 15 required, 15 present, 0 missing
- endpoints[].path_params: 16/16 present inside backticked §4 paths
- Invoice line sub-fields 10/10; roles 7/7; error ids 30/30; enum values 84/84 (incl. all line kinds and origins)

**Contract 2 — Rule Coverage: PASS**
- validations[] with priority: 30/30 expressed; the full priority pipeline (auth → forbidden → shape → existence → OCC → state → 24 business gates in scaffold priority order) is stated in §2.8, and per-endpoint orders are restated in §3 (start-work's six gates, permit activation's four checks, JHA approve stale-version-before-segregation)
- concurrency_rules[] OCC rejections: 2/2 expressed (`expected_site_version` on schedule activation, `expected_job_version` on JHA approval; both carry `ERR_STALE_VERSION` / HTTP 412; explicit statement that no other endpoint accepts a version field)
- state_machines[].transitions: 55/55 fully expressed (from/to states, preconditions paired with error ids, side effects incl. every `version` increment — two missing increment notes on start-work and generate-invoice were found in the audit walk and repaired)
- calculations[]: 10/10 expressed in precise prose with all constants (8-hour regular window, grace 30/60/0/0/0 by cause, 480-minute daily cap, 15-minute blocks, 500000/2000000-cent tiers at 3%/7%, 2% environmental fee, 10.00 variance threshold, 0.9500 capture threshold) and both forbidden-order worked examples (38986 vs 38985; 494700 vs 510000)
- validations[] conditions: 30/30 matchable to their `error_id` in §2/§3 prose; every multi-endpoint `applies_to` scope enumerated (six job-state-gated creates explicitly bound to `ERR_INVALID_STATE` during repair)
- endpoints[].side_effects: all expressed, including the three-link profile-suspend cascade, invoice-void double revert, job-cancel four-way cascade, and the two daily-close sweeps
- entities[].fields[] structured content: all defaults, numbering schemes (`revision_number`/`sequence` max+1, `INV-<job creation sequence>-<regeneration count>`, `L<n>` line ids) and precision rules reconstructible from prose
- sibling-branch symmetry: 11 parallel groups checked (cancel ×5 states, permit activate ×2, revoke ×3, expire ×3, manifest void ×2, receive/verify branches, UNIT_RATE/TIME_AND_MATERIALS, WEIGHT/VOLUME, five grace causes, two discount tiers, invoice void ×2) — all rendered with equal density

**Contract 3 — §3 Path Purity: PASS**
- backtick tokens scanned: 637
- tokens starting with `/`: 0 · bare HTTP-method tokens: 0 · method+path combined tokens: 0

**Additional checks:** §2.2 block is byte-identical to `section-2.2-response-structure.md`; pseudocode/fuzzy-word scan clean (no `>=`/`==`/`!=`/`+=`/`->`, no "approximately/roughly/conservatively"); the forbidden SCAFFOLD_DIFFICULTY_DESIGN.yaml and SCAFFOLD_CORNER_DESIGN.yaml were never opened.

## Step 6: Generate Implementation — 2026-08-14T10:55:00.000Z

Implementation complete. Summary:

## Files written (22, all under `/home/ubuntu/github/CodingPRD/tasks/task_1694_industrial_vacuum_hydroblasting_services/workspace/implementation/`)

- `start.sh` — executable launcher; guarded dependency install (`python3 -c "import flask"` check, so per-test reboots skip pip), `exec python3 app.py` in foreground, binds `0.0.0.0:$PORT` (default 10000)
- `requirements.txt` — `flask>=3.0,<4.0` (already satisfied on the host)
- `app.py` — Flask app assembly, blueprint registration, envelope-shaped 404/405/500 handlers
- `db.py` — in-memory store (16 dicts + logical clock defaulting to `2026-08-01T00:00:00Z` + job creation sequence counter); **nothing seeded at startup** (verified: fresh boot returns empty lists)
- `errors.py`, `response.py`, `middleware.py`, `util.py` — error catalog, `{meta, response_type, data}` envelope with `limit/offset/total_count/has_more` pagination, `X-User-ID`/`X-User-Role` auth (401/403), Decimal/round-half-up + ISO-8601 helpers
- `services/calculations.py` — downtime billing (grace by cause, 480-min daily cap on `closure_day`, 15-min ceil blocks, single round-half-up), invoice line builder for UNIT_RATE (VACUUM/HYDRO + AUTO_MINIMUM floor) and TIME_AND_MATERIALS (LABOR_REG 8h split + LABOR_OT × multiplier + EQUIPMENT), pinned per-line-then-sum rounding, volume-discount tiers (≥2M → 7%, ≥500K → 3%, pre-discount base), 2% environmental fee, facility reservation/posture recompute, standby accrual
- `routes/` — 13 modules covering all resource groups

## Endpoint count: 87

All endpoints from the scaffold §1.5 table: 16 resource groups (sites, rate-schedules, jobs, jhas, permits, equipment-units, operators, assignments, waste-profiles, disposal-facilities, manifests, containment-records, downtime-events, invoices + line sub-resource, incidents) plus the two ops endpoints (`/v1/sites/{id}/daily-close`, `/v1/_clock/set_current_utc`).

## Key behaviors verified by smoke tests (all passing on fresh processes)

- Validation pipeline order: 401 → 403 → 400 (shape incl. assignment FK-kind match) → 404 → 412 OCC → 409 state → business gates in §2.8 order (containment before downtime-open at complete-field-work per §2.8's fixed pipeline)
- OCC: `expected_site_version` on schedule activation, `expected_job_version` on JHA approve (412 before business gates); SoD (422) on JHA approve/reject and profile approve
- Job parallel dimensions: start-work six gates in order (stop → JHA → confined-space permit → pressure rating → operator cert → credit hold); stop-work/resume with permit suspend cascade and incidents-closed precondition; SERIOUS/MAJOR incident auto-stop
- Assignment window_hours (2dp), HAZWOPER coverage, half-open equipment overlap (adjacency allowed), 10h operator rest buffer (exactly 10h allowed)
- Manifests: estimated_tons 2dp, WEIGHT vs VOLUME variance with |variance| ≤ 10.00 → RECEIVED else EXCEPTION, facility reserved-ledger with FULL/AVAILABLE posture, capacity equality allowed, profile-suspend and job-cancel cascades releasing reservations
- Downtime billing verified numerically (grace, daily cap 480, blocks, amounts); invoice engine verified including the PRD's two pinned examples (two 1.0h OT lines at 12995×1.5 → 19493+19493=38986; exactly-500000 discountable → total 494700); void cascade reverts job INVOICED→FIELD_COMPLETE and un-bills downtime; regeneration numbering `INV-<jobseq>-<n>`
- Daily-close sweeps (permit EXPIRED when `valid_until < now`, stale SCHEDULED assignment cancel when `window_start + 24h < now`), logical clock echo format `2026-08-01T00:00:00Z`

## Boot confirmation

`bash start.sh` from `./implementation/` boots cleanly from a fresh process (verified 4 times on separate ports, including after `pycache` removal): responds within ~3s, binds 0.0.0.0, empty store, all smoke servers shut down afterwards.

## Step 5 (first attempt): Generate Unit Tests — 2026-08-14T10:55:00.000Z

The Step 5 subagent completed its full PRD-first audit of all 21 §1.8 difficulty instances and all 54 non-stub §1.9 corner instances (verdict: all KEEP, 9 stubs resolve, planned 96 tests) but exited prematurely — its final message ended at "Now let me write the Stage 1 helpers" with NO files written to test_helpers/ or test_suite/ (verified empty on disk). Orchestrator resumed the same agent (context intact) to complete the file-writing stage.

## Step 5: Generate Unit Tests — 2026-08-14T11:15:00.000Z

All clean. Generation complete.

## Summary

**Files written** (under `/home/ubuntu/github/CodingPRD/tasks/task_1694_industrial_vacuum_hydroblasting_services/`):

Stage 1 — `test_helpers/` (1,613 lines):
- `types.py` (418) — 15 entity TypedDicts + 20 status/role enums
- `api_client.py` (334) — one method per PRD §4 endpoint (incl. daily-close and logical clock)
- `api_errors.py` (74) — 30 `ApiErrorId` members + HTTP status map registered via `set_error_http_status_map`
- `assertions.py` (182) — per-entity `assert_*` + invoice totals invariant
- `factories.py` (187), `constants.py` (53, grace table/480-min cap/tiers/thresholds), `test_users.py` (49, opaque roles + `make_*` builders for SoD tests), `fixtures.py` (277, five tiers: site+schedule spine, JHA OCC approval, IN_PROGRESS/FIELD_COMPLETE/INVOICED lifecycle, waste chain, clock-driven downtime), `__init__.py` (39)

Stage 2 — `test_suite/` (3,089 lines): `conftest.py` + 14 test files (`test_01` entities/retrieval → `test_14` validation order/consistency).

**Test counts:**
- Queue A (§1.8 difficulty): 21/21 instances × 2 tests = **42 tests**
- Queue B (§1.9 corner): 54/54 non-stub instances × ≥1 test = **65 tests**
- **Total: 107 tests**, all collected cleanly by pytest

**Instances skipped:** none. All 21 difficulty and all 54 non-stub corner instances passed the PRD-first two-condition filter (verbatim coverage + unique derivability). The 9 `excluded_because:` stubs were not translated; all their `difficulty_instance` pointers resolve to real §1.8 instances.

**Stage-gate audit results (all pass):**
- Coverage: every §1.8 instance has exactly ≥2 tagged tests; every non-stub §1.9 instance has ≥1; zero unknown/dangling tags; zero stub translations.
- Per-test: all 107 functions have a docstring ending in exactly one `Design: Difficulty/...` or `Design: Corner/...` line copied verbatim from the source yaml `name:` (AST-verified, tag is the terminal docstring line).
- Verbatim citation sweep: every docstring's quoted PRD sentence greps in `workspace/PRD.md` (one audit-script false positive was manually re-verified verbatim).
- No `pytest.mark.skip`/`skipif`/`xfail`; no "scaffold" references in generated code; no freelance tests beyond the two design indices.
- All files compile; `test_helpers` imports standalone; `pytest --collect-only` reports 107 tests, 0 errors.

## Step 7: Run Tests and Iterate — 2026-08-14T11:55:00.000Z

## Summary

**Final state: clean 8-round parallel sweep — all 8 rounds 107/107 passed** (verified from `results.1.json` … `results.8.json` in `workspace/implementation/`).

**Iterations run:** 4 sweep launches (rounds 1–3 were disrupted by shared-host process kills — a foreign agent's `pkill -f "python3 app.py"` and harness reaping killed sweep trees mid-run; the final sweep used a `setsid`-detached self-healing driver that re-runs only rounds whose results file is missing). Substantively: 2 full diagnostic iterations — iteration 1 produced the single deterministic failure, iteration 2 (post-fix) passed 8×107, and the final driver sweep re-confirmed 8×107 with persisted results files.

**Tests deleted:** none. The one failing test traced to a verbatim PRD §3.7 rule with unique derivability — the defect was in the test's own setup, so deletion was not warranted.

**Fixes applied to `test_helpers/`:** none — factories, fixtures, role headers, and assertion library all proved consistent with PRD.

**Fixes applied to `test_suite/`:**
- `test_suite/test_13_invoicing.py` — `_combined_field_complete()` helper: added `"job_type": "COMBINED"` to `job_overrides`. The helper's docstring, crew (`"both"` = COMBO unit + hydroblast-certified operator), `pressure_plan=True`, and dual VACUUM+HYDRO line expectations all described a COMBINED job, but the override omitted `job_type`, so the factory default (`VACUUM`) silently applied and the implementation correctly emitted only a VACUUM line. With the fix, the asserted totals (subtotal 1,216,000 / discount 36,480 / env fee 23,590 / total 1,203,110; T&M variant 292,000/0/5,840/297,840) follow exactly from PRD §3.7's line-construction and pinned rounding order.

**Fixes applied to `implementation/`:**
- `workspace/implementation/routes/permits.py` — added the missing `ERR_INVALID_WINDOW` import (used at line 43 in `create_permit` for the PRD §3.3 "end at or before the start is rejected with `ERR_INVALID_WINDOW`" check). Latent `NameError`→500 on that path; no current test exercised it, fixed proactively since the check is PRD-required. Verified no other route references an unimported `ERR_*` name (static cross-check of all route files).

**Flakiness notes:** two apparent "extra" failures in early sweep logs (`test_tm_invoice_bills_crew_windows_and_diverges`, `test_exactly_500k_...`, `test_manifests_filtered_...`) were log-interleaving artifacts from 8 pytest processes sharing one stdout file — the authoritative per-round results files showed each passing in every round. No genuine flaky test was observed.

## Step 8: Finalize PRD — 2026-08-14T12:05:00.000Z

Analysis complete. `PRD_FINALIZED.md` has been produced at `workspace/PRD_FINALIZED.md` and is byte-identical to `PRD.md` — the anticipated valid outcome.

## Summary

**Line counts and delta:** PRD.md 350 lines; PRD_FINALIZED.md 350 lines; 0% delta (byte-identical).

**Changes made:** none. Zero edits were committed.

### Per-diff-item analysis (why each required no PRD change)

**Item 1 — test_suite fix: `test_suite/test_13_invoicing.py`, `_combined_field_complete()` added `"job_type": "COMBINED"` to `job_overrides`.**
- Subject: UNIT_RATE invoice line construction for COMBINED jobs.
- Impl paths enumerated: `workspace/implementation/services/calculations.py:176-189` (`build_invoice_lines` — VACUUM line emitted when `job["job_type"] in ("VACUUM", "COMBINED")`, HYDRO line when `in ("HYDROBLAST", "COMBINED")`, then AUTO_MINIMUM shortfall logic); `workspace/implementation/routes/invoices.py` (lifecycle/totals only, no job_type branching); `test_helpers/factories.py:61` (factory default `"job_type": "VACUUM"`, confirming the test helper's omitted override silently produced a VACUUM job).
- PRD verification: PRD §3.7 (line 209) already pins the behavior verbatim — "a `VACUUM` line for `VACUUM` and `COMBINED` jobs bills `gallons_removed` at the pinned schedule's `vacuum_per_gallon_cents`, and a `HYDRO` line for `HYDROBLAST` and `COMBINED` jobs bills `feet_cleaned` at `hydroblast_per_foot_cents`." The asserted totals (1,216,000/36,480/23,590/1,203,110) follow exactly from §3.7's pinned rounding order (line 215) and §2.6's per-line rounding.
- Verdict: pure fixture bug. The PRD uniquely determines the behavior and the implementation matches it. No PRD silence, no mismatch — no edit.

**Item 2 — implementation fix: `workspace/implementation/routes/permits.py`, added missing `ERR_INVALID_WINDOW` import (used at line 43 in `create_permit`).**
- Subject: permit validity-window validation on creation.
- Impl paths enumerated: `routes/permits.py:43-45` (the fixed site: `if not valid_until > valid_from: raise unprocessable(ERR_INVALID_WINDOW, ...)` — i.e., end at or before start rejected); also read `activate_permit` (permits.py:94-97, uses the distinct `ERR_PERMIT_WINDOW_INVALID` for the clock-outside-window check, matching PRD line 160) and the full file for the remaining transitions. Static cross-check of all 13 route files plus `errors.py` confirmed every `ERR_*` name referenced anywhere in `implementation/routes/` is now imported (script output: all files "ok"), so no sibling latent-500 path exists that might have implied divergent behavior.
- PRD verification: PRD §3.3 (line 158) already contains the rule verbatim — "a validity window from `valid_from` to `valid_until`; an end at or before the start is rejected with `ERR_INVALID_WINDOW`." The fix aligned the implementation TO the existing PRD rule; the PRD was never silent and never contradicted.
- Verdict: impl-to-PRD conformance fix. No edit.

Both items satisfy the zero-diff conditions the task brief anticipated, so the pre-edit search log requirement is discharged by the per-item analyses above.

## Step 9: Complete PRD — 2026-08-14T12:20:00.000Z

Done. `workspace/PRD_COMPLETED.md` is written — a minimal patch over PRD_FINALIZED.md, verified by diff (24 hunks, all intended).

**Size delta:** PRD_FINALIZED.md 350 lines / 55,009 chars → PRD_COMPLETED.md 352 lines / 58,264 chars (+2 lines, +3,255 chars; the +2 lines are the one new paragraph in §2.2 plus its blank separator).

**Counts:** 24 ambiguity-pins, 2 mismatch-revisions (26 edits total across 24 hunks).

**Changes:**

- §2.1 — insert — ambiguity — `X-User-ID` empty string treated as missing → `ERR_UNAUTHENTICATED` — implementation/middleware.py:27
- §2.2 — insert — ambiguity — undefined path → `ERR_NOT_FOUND` 404; unsupported method on a defined path → `ERR_NOT_FOUND` at 405 — implementation/app.py:38-44
- §2.3 — insert — ambiguity — ties on `created_at` preserve creation order; out-of-range/non-integer `limit`/`offset` → `ERR_INVALID_REQUEST`; `has_more` true iff `offset`+`limit` < `total_count` — implementation/util.py:249-270, implementation/response.py:20
- §2.4 — revise — ambiguity — `version` starts at 1 at creation (was unpinned) — implementation/util.py:216
- §2.5 — revise — ambiguity — clock feeds entity `created_at`/`updated_at`; `to_iso8601` without offset read as UTC; `current_utc` rendered at seconds precision when whole, else 3 fractional digits — implementation/util.py:27-51,211-224, implementation/routes/ops.py:54-59
- §2.5 — insert — ambiguity — daily-close `expired_permit_ids`/`cancelled_assignment_ids` listed in affected resources' creation order — implementation/routes/ops.py:25-47
- §2.6 — revise — ambiguity — `window_hours` rounded half up to two decimals — implementation/routes/assignments.py:113
- §2.8 — insert — ambiguity — malformed/non-object JSON body fails request-shape step; absent body treated as empty object; unrecognized fields ignored — implementation/util.py:118-137
- §3.1 — revise — ambiguity — site PATCH increments `version` by one on every call, whether or not the value changes — implementation/routes/sites.py:57-68
- §3.1 — insert — ambiguity — every rate-card field except `overtime_multiplier` required; five rates non-negative integers; `overtime_multiplier` when supplied must be > 0 — implementation/routes/sites.py:77-86
- §3.2 — revise — ambiguity — `estimated_gallons` pinned as non-negative integer — implementation/routes/jobs.py:48-49
- §3.2 — revise — ambiguity — new jobs carry `gallons_removed` and `feet_cleaned` at zero — implementation/routes/jobs.py:66-67
- §3.2 — revise — ambiguity — all four equipment fields required, `max_pressure_psi`/`tank_capacity_gal` non-negative integers; all four operator fields required — implementation/routes/registry.py:20-23,57-60
- §3.2 — insert — ambiguity — assignment's non-matching foreign key stored and returned as null — implementation/routes/assignments.py:117-118
- §3.3 — insert — ambiguity — JHA pressure-plan fields optional at authoring (enforced at submission); types when supplied — implementation/routes/jhas.py:36-38
- §3.3 — revise — **mismatch** — revise returns REJECTED → DRAFT with fields unchanged (PRD claimed the plan "can be corrected"; impl has no JHA update operation) — implementation/routes/jhas.py:144-152
- §3.4 — revise — ambiguity — incident close requires `osha_recordable` boolean and `corrective_action` non-empty string (empty also rejected) — implementation/routes/incidents.py:88-93
- §3.5 — revise — ambiguity — `duration_minutes` floored at zero if the clock reads earlier than `started_at` at close — implementation/services/calculations.py:120-122
- §3.6 — insert — ambiguity — `density_lbs_per_gal` must be > 0; `disposal_rate_per_ton_cents` a non-negative integer — implementation/routes/waste.py:35-36
- §3.6 — insert — ambiguity — `total_capacity_tons` zero or greater — implementation/routes/waste.py:141-142
- §3.6 — insert — ambiguity — manifest `estimated_gallons` a positive integer — implementation/routes/manifests.py:36
- §3.6 — insert — ambiguity — `received_tons` a number, zero or greater — implementation/routes/manifests.py:116
- §3.6 — revise — ambiguity — `resolution_note` missing/empty/non-string all rejected; `adjusted_tons` a non-negative number — implementation/routes/manifests.py:160-163
- §3.7 — revise — ambiguity — invoice_number semantics: platform-wide one-based job creation counter; one-based per-job regeneration count including voided invoices (first invoice is INV-<n>-1) — implementation/routes/jobs.py:56,69,312-317, implementation/db.py:30-31
- §3.7 — insert — ambiguity — line `unit` values per kind; STANDBY line carries `billed_blocks` qty at quarter standby rate (rounded) while `amount_cents` stays the event's; DISPOSAL line qty `billed_tons` at profile rate; LABOR_OT `rate_cents` is the straight labor rate; AUTO_MINIMUM qty 1 with rate = amount — implementation/services/calculations.py:181-243
- §3.7 — revise — **mismatch** — corrective-line append accepts any integer amount (negatives permitted), carries qty 1/`each`/rate = amount, and returns `201 Created` with the updated invoice (vs §4's 200-for-modification rule, since lines are sub-objects per §2.4) — implementation/routes/invoices.py:86-110

**Notable non-changes (impl verified consistent with existing PRD pins):** all endpoint paths/roles (§4 table), the §2.8 validation/business-gate pipeline order (impl follows it everywhere, including cert-before-window in assignments and containment-before-downtime in complete-field-work), both OCC writes, all state machines, downtime grace/cap/block math, invoice tier/discount/env-fee order with the pinned 494700 example, WEIGHT vs VOLUME variance formulas and rounding order, the §2.9 reservation ledger, and all cascade semantics.
