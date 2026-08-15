# Worklog — task_1620_conservation_easement_land_trust

Scenario: Conservation Easement & Land Trust Stewardship (land trust stewardship program): easement terms & permitted-use matrix, baseline documentation report, annual monitoring visit & violation detection, amendment/discretionary approval process, landowner succession & notice, enforcement & remediation agreement, stewardship endowment accounting, appraisal & tax-deduction substantiation

## Step 1: Create Task Directory — 2026-08-14T02:17:00.000Z

Directory `tasks/task_1620_conservation_easement_land_trust/workspace/` pre-created and pre-assigned by the pipeline dispatcher. Step 1 treated as DONE per invocation instructions.

## Step 2: Generate Scaffold — 2026-08-14T03:12:30.000Z

All three scaffold artifacts are generated, lint-clean, and self-consistent. No sibling task directories were inspected; the design is derived solely from the scenario text and the skill specification.

## Output files (in `/home/ubuntu/github/CodingPRD/tasks/task_1620_conservation_easement_land_trust/`)

| File | Lines | Contents |
|---|---|---|
| `SCAFFOLD.yaml` | 1110 | §1.0–§1.7 (envelope verbatim; no difficulty/corner keys) |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 625 | single key `scaffold_difficulty_design:` (§1.8) |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 1102 | single key `scaffold_corner_design:` (§1.9) |

## Counts

- **Entities:** 12 (Easement, Landowner, BaselineReport, MonitoringVisit, Violation, AmendmentRequest, UseAuthorization, EnforcementAction, SuccessionNotice, Appraisal, EndowmentFund, EndowmentTransaction [immutable append-only])
- **Endpoints:** 65 (flat topology under `/stewardship`, plus test-driving `POST /_clock/set_current_utc` with pinned default `2026-08-01T00:00:00Z`)
- **State machines:** 11 — including 4 cyclic (BaselineReport revision loop, AmendmentRequest submit/revise loop, EnforcementAction breach→renegotiate loop) and posture-driven gating on Easement (`posture` computed: ENFORCEMENT_ACTIVE > VIOLATION_OPEN > MONITORING_DUE > GOOD_STANDING)
- **Calculations:** 8 — incl. dual-variant draw capacity (unitized vs policy) and deductible value (standard vs enhancement-adjusted); combinatorial modes (a) waterfall draw allocation, (b) pinned nested-rounding unitization, (c) pinned-order carryover; weighted materiality score; date-threshold monitoring/cure rules
- **Validations:** 12 ordered priority rows spanning auth → existence → state → OCC → SoD → uniqueness → domain → temporal → referential → fiscal
- **Error catalog:** 50 codes (2×400, 2×402, 6×403, 11 typed 404s, 16×409, 2×412 OCC, 11×422)
- **Roles:** 6, segregation-of-duties model (Landowner is `entity_backed:Landowner`; four SoD pairs: prepare/accept, detect/resolve, execute/complete, submit/approve)
- **OCC concurrency rules:** 3 (amendment create, succession record on `Easement.version`; draws on `EndowmentFund.version`) — all true races per §1.2.1's serial-observability filter
- **§1.8 difficulty instances:** 19 (all 9 rules × ≥2; rule 2 has 3 covering modes a/b/c); every formula-derived assert pre-computed to literals (e.g., units 810.8123 vs wrong-order 810.8122; carryover allowance 32000 vs forbidden-order 24000; waterfall splits {15000, 285000, 0} and {0, 95000, 55000})
- **§1.9 corner instances:** 65 entries (54 active with full test recipes + 11 `excluded_because:` stubs that resolve to §1.8 instance names), covering all 9 claim-extraction-guide sections; all 50 error codes have at least one trigger

## Lint verdict (verbatim)

```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```
(65 endpoints, 12 entities, 19 §1.8 + 54 §1.9 active instances, 576 calls scanned.)

Additional gates passed: forbidden-vocabulary scan clean; file-split discipline verified; every error referenced in §1.1–§1.5; all `${var}` placeholders bound by earlier `captures:`; all OCC `expected_*_version` payloads reference captured versions; cross-file instance names unique; all exclusion stubs cite existing §1.8 instances.

Difficulty levers (per the harder-than-expert request): depth-3 clock-sweep cascade (violation→enforcement→posture), depth-2 amendment-approval cascade auto-denying use authorizations, dual-variant calculations on two entity domains, two distinct interval-overlap semantics (half-open monitor windows vs 365-day appraisal buffer), two conserved-quantity invariants (ledger cents/units; exactly-one-ACTIVE-landowner), priority conflicts on two different error-category pairs, and boundary checks on score (=70), dates (due-day inclusive, deadline-day curable), and single-cent principal invasion.

## Step 3: Copy Shared Files — 2026-08-14T03:14:30.000Z

Copied `./INSTRUCTION.md` → `tasks/task_1620_conservation_easement_land_trust/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-14T03:45:00.000Z

All checks pass. The PRD is complete and verified. Here is the final summary.

## Summary

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_1620_conservation_easement_land_trust/workspace/PRD.md` — **362 lines**

**Section structure:**
- §1 Introduction (2 paragraphs, business-context angle)
- §2 Global Specifications: 2.1 RBAC (6 roles, identity translations incl. entity-backed `Landowner`), 2.2 API Response Structure (**byte-identical verbatim block**, verified programmatically), 2.3 Pagination, 2.4 Resource Identity/Versioning (incl. `EndowmentTransaction` append-only exception), 2.5 Easement Posture Gate, 2.6 Permitted-Use Matrix, 2.7 Money/Units/Precision, 2.8 OCC (all 3 rules), 2.9 Validation Pipeline (12-step ordered precedence), 2.10 Logical Clock & Sweeps, 2.11 Segregation of Duties
- §3 Business Logic: 9 subsections (drafting/baseline/recordation, monitoring calendar, violations, enforcement, use authorizations, amendments/materiality/cascade, succession, appraisals, endowment unitization/draws/close-year)
- §4 Endpoint Definitions (4-column table), §5 Error Code Catalogue (2-column table)

**Coverage vs. scaffold:**
- Entities: 12/12 (all fields rendered in narrative, incl. computed/derived)
- Endpoints: 65/65 in §4 table; all side effects narrated in §3
- Calculations: 8/8 fully expressed in precise prose (pinned rounding order, waterfall buckets, carryover 4-step order + forbidden-order warning, materiality components with 70/69 boundary, both deductible variants, cure-deadline and monitoring-due boundary inclusivity)
- Validations: 12/12 priority categories, with per-endpoint pipeline-order statements in §3
- Errors: 50/50 in §5 table and each referenced in §2/§3 prose
- State machines: 11/11; all 42 transitions with preconditions, side effects, and cascades; 51/51 state/enum strings present
- Concurrency rules: 3/3 (write capability + `expected_easement_version`/`expected_fund_version` + exact error id + HTTP 412)

**Zero-Silence / Hard-Contract audit:**
- Contract 1 (Field-Name Coverage): 113 required identifiers (94 entity fields + endpoint inputs/query/path params), 113 present, 0 missing — **PASS** (path-param names added to §2.9 step 3 after first pass flagged them)
- Contract 2 (Rule Coverage): priority orderings, OCC rejections, transitions, calculations, validation-condition↔error pairings, endpoint side effects/applies-to, field-level structured content, sibling-branch symmetry — all expressed; 0 missing — **PASS**
- Contract 3 (§3 Path Purity): 549 backticked tokens scanned, 0 path/method violations — **PASS**; no fuzzy/approximating words or operator pseudocode tokens in §3

No forbidden files were opened (SCAFFOLD_DIFFICULTY_DESIGN.yaml and SCAFFOLD_CORNER_DESIGN.yaml untouched; no other task directories read). PRD.md ends at §5 with no audit footer.

## Step 5: Generate Unit Tests — 2026-08-14T04:35:00.000Z

Generation complete for task_1620_conservation_easement_land_trust. All artifacts are under `/home/ubuntu/github/CodingPRD/tasks/task_1620_conservation_easement_land_trust/`.

## test_helpers/ (9 files)
- `types.py` — 6 role enums + 14 status/field enums + 13 entity TypedDicts; `EndowmentTransaction` correctly carries only `id` + `created_at` (no `updated_at`/`version`) per PRD §2.4
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per endpoint (53 methods incl. `/_clock/set_current_utc`); `api_client` singleton
- `api_errors.py` — all 50 PRD §5 error IDs + HTTP map, registered via `set_error_http_status_map`
- `assertions.py` — per-entity `assert_*` validators; `assert_endowment_transaction` asserts absence of `version`/`updated_at`
- `factories.py` — payload factories, input fields only; optional fields omitted unless supplied (so server defaults are exercised)
- `constants.py` — cure days, materiality weights/threshold, 30/45-day succession windows, 365/60/240-day appraisal windows, 100.0000 unit anchor, standard matrix literals
- `test_users.py` — `TEST_USERS` constants + `make_<role>_headers` builders; `make_landowner_headers(landowner_id)` for the entity-backed Landowner role (used by all ownership-gated calls)
- `fixtures.py` — composite chains: `create_recorded_easement` (easement→landowner→baseline→submit→accept→record), violation state builders (OPEN/NOTICE_SENT/CURE_IN_PROGRESS/ESCALATED with spawned enforcement), `setup_active_fund`, `setup_delivered_appraisal`, succession/appraisal/amendment creators, `set_clock`, version getters
- `__init__.py` — barrel re-export

## test_suite/ (13 files)
`conftest.py` + 12 numbered test files (01 creation/recordation, 02 envelope/404s, 03 baselines, 04 monitoring, 05 violations, 06 enforcement, 07 use-authorizations, 08 amendments, 09 succession, 10 appraisals, 11 endowment, 12 cross-entity reachability).

## Test counts
- **Total: 92 tests** — collected cleanly by `pytest --collect-only`; all files byte-compile
- **Queue A (§1.8 Difficulty): 38 tests** — all 19 instances × exactly 2 tests
- **Queue B (§1.9 Corner): 54 tests** — all 54 non-stub instances × 1 test; 11 `excluded_because:` stubs not translated (all cross-references verified to resolve to real difficulty instances)

## Skipped / narrowed instances
- No instance was fully skipped. One instance was narrowed on the PRD-first filter: `Corner/endpoints/fk_reverse_reachability_filtered_lists` — its violations-by-`easement_id` filter branch has no PRD coverage (§4 says only "List violations"; §3.3 states no violation filters), so the test asserts only the two PRD-verbatim branches (succession-notice `successor_landowner_id` filter per §3.7, fund ledger sub-resource per §3.9) and documents the omission in the module docstring.
- Two corner instances asserted `required_photo_points` values captured from *create* responses; PRD says the value is "recomputed from the easement's current acreage at submit time", so its pre-submit value is not uniquely derivable. Both tests (`baseline_submit_incomplete_rejected`, `required_photo_points_floor_and_ceiling`) pin the bar behaviorally instead: N-1 photo points reject with `ERR_INCOMPLETE_BASELINE`, exactly N submit succeeds (bar pinned to 4 at 250 ac and 5 at 500 ac).

## Docstring-tag audit (scripted, AST-based)
- 92/92 tests carry exactly one `Design:` tag as the final docstring line; 0 untagged, 0 dual-tagged, 0 unknown tags, 0 stub translations
- Coverage: every Difficulty instance ≥2 tests, every non-stub Corner instance ≥1 test
- PRD-citation pass: all 155 quoted citation spans verified verbatim against `workspace/PRD.md` (whitespace-normalized containment); 9 initially non-verbatim quotes (ellipses/bullet-boundary issues) were rewritten to full verbatim sentences and re-verified
- 4th-decimal unit assertions use `pytest.approx(..., abs=1e-9)` so the pinned rounding orders (810.8123 vs 810.8122, UV 123.3331) are actually discriminating

## Step 6: Generate Implementation — 2026-08-14T04:35:00.000Z

Done. The implementation is complete and verified.

## Summary

**Files created** (all under `/home/ubuntu/github/CodingPRD/tasks/task_1620_conservation_easement_land_trust/workspace/implementation/`):
- `start.sh` — guarded pip install (no-op when Flask present), `exec python3 app.py`, foreground
- `requirements.txt` (flask)
- `app.py` — entry point, global request lock, blueprint registration, envelope-formatted error handlers (ApiError/404/405/500), binds `0.0.0.0:$PORT` (default 10000)
- `db.py` — in-memory dicts for all 12 entity tables + logical clock (default exactly `2026-08-01T00:00:00Z`); **no seeding anywhere**
- `errors.py`, `response.py` (envelope: `meta.api_request_id`/`api_request_timestamp`, `response_type`, `data`; list meta adds `limit`/`offset`/`total_count`/`has_more`), `middleware.py` (X-User-ID/X-User-Role validation, 6 roles, pagination limit default 10 min 1 max 100)
- `utils.py` — strict YYYY-MM-DD parsing, month-end-clamped month arithmetic, Decimal half-up helpers
- `services/domain.py` — posture derivation (ENFORCEMENT_ACTIVE > VIOLATION_OPEN > MONITORING_DUE > GOOD_STANDING), computed counts, pinned unitization (round units → apply → revalue), waterfall draw allocation (literal nested min/max incl. the 402 branches), pinned 4-step carryover, materiality scoring, escalation cascade, clock sweep
- `routes/` — 12 blueprints: easements, landowners, baselines, visits, violations, enforcement, amendments, use_authorizations, succession, appraisals, endowment, clock

**Counts:**
- **65 endpoints** implemented — the full SCAFFOLD §1.5 table (64 business routes under `/stewardship` + `POST /_clock/set_current_utc`)
- **11 state machines** (Easement, Landowner, BaselineReport, MonitoringVisit, Violation, AmendmentRequest, UseAuthorization, EnforcementAction, SuccessionNotice, Appraisal, EndowmentFund), with all preconditions, side effects, and cascades (escalation spawns PROPOSED EnforcementAction; enforcement completion resolves the ESCALATED violation; amendment approval rewrites the matrix and auto-denies frozen authorizations with `AMENDMENT_SUPERSEDES`; succession record flips ACTIVE/SUPERSEDED atomically)
- **8 calculations**: unit_value_unitization (pinned 3-step rounding), draw_capacity (provisional vs final variants), carryover_allowance (pinned 4-step order, closed-year cap), waterfall_draw_allocation, deductible_value (standard/enhancement-adjusted), amendment_materiality_score (half-up, BOARD at >= 70), monitoring_schedule (month-end clamp, inclusive on-time boundary), cure_deadline (90/30/7, exclusive escalation boundary)

**Fidelity details honored:** validation pipeline priority order (auth → existence → state → cross-gates → OCC → SoD → uniqueness → domain → temporal → referential → draw authority); OCC fields `expected_easement_version` (amendment create, succession record, 412) and `expected_fund_version` (draws, 412); SoD pairs (prepare/accept, detect/resolve, execute/complete, submit/approve); assignment anchors (monitor, appraiser); landowner identity = current_landowner_id; EndowmentTransaction carries only `id` + `created_at` (no version/updated_at); `unit_value_cents` null while units_outstanding == 0 with the 100.0000 anchor used internally; role-bound approve/reject lanes (wrong role+state pairing → 409).

**Boot verification:** ran `bash start.sh` on a fresh port — server booted, bound 0.0.0.0, returned the correct envelope on `GET /stewardship/easements` (200, empty array, clock default `2026-08-01T00:00:00.000Z`), 400 on missing auth headers, 404 envelope on unknown route, then was killed. Two end-to-end smoke suites (covering the full record→monitor→violation→enforce→amend→succeed→appraise→endowment→clock-sweep lifecycle, waterfall buckets, carryover freeze, unitization rounding chain, OCC 412s, freeze conflicts, overlap rules) passed — the only two smoke-script failures were wrong expectations in my throwaway test script itself (a violation created against a cell an approved amendment had already flipped to PROHIBITED correctly returned 201), not server bugs.

## Step 7: Run Tests and Iterate — 2026-08-14T04:50:00.000Z

## Summary

**Result: clean 8-round parallel sweep — 92/92 passed in every round (rounds 1-8).**

- **Iterations run:** 2 (iteration 1: 91/92 in all 8 rounds, one deterministic failure; iteration 2 after fix: 92/92 × 8).

- **Tests deleted:** none.

- **Fixes applied to `test_helpers/`:** none.

- **Fixes applied to `implementation/`:** one.
  - File: `/home/ubuntu/github/CodingPRD/tasks/task_1620_conservation_easement_land_trust/workspace/implementation/services/domain.py`, function `post_ledger`.
  - **What was wrong:** the ledger entry's `units` field was stored negated for `DRAW` transactions (`-1090.9091`), while `test_fund_ledger_conservation_across_posting_types` (test_11_endowment_funds.py) expects the positive delta `1090.9091`.
  - **PRD basis (STEP 1/2/3):** PRD §3.9 states verbatim: "the units delta is computed as the posting's **absolute** `amount_cents` divided by the current `unit_value_cents`" and "a `DRAW` **subtracts** its units delta" — and the ledger records "signed `amount_cents`, computed `units`", attaching "signed" only to `amount_cents`. The delta is therefore non-negative by definition; the subtraction applies at the aggregates. A negative stored delta would make "subtracts its units delta" grow `units_outstanding`, contradicting the same sentence — so unique derivability holds, the test is faithful, and the bug was in the implementation.
  - **Fix:** store `units_delta` (positive) for both `CONTRIBUTION` and `DRAW`; `INVESTMENT_RETURN` remains `0.0000`. Aggregate math (`units_outstanding -= units_delta` on draws) was already correct and untouched. Verified no other code reads the stored `units` field besides the serializer.

## Step 8: Finalize PRD — 2026-08-14T04:55:00.000Z

## Summary

**Produced:** `/home/ubuntu/github/CodingPRD/tasks/task_1620_conservation_easement_land_trust/workspace/PRD_FINALIZED.md` — byte-identical copy of `PRD.md` (verified with `cmp`).

**Line counts:** PRD.md = 361 lines, PRD_FINALIZED.md = 361 lines, delta = 0 (0.0%).

**Changes:** none. Zero PRD edits — the single Step 7 item was an implementation bug fix toward PRD prose that already uniquely derives the correct behavior, so no PRD silence or PRD mismatch exists to pin.

### Step 7 diff item analysis (the only item)

- **Fix:** `implementation/services/domain.py`, `post_ledger` — the ledger entry's stored `units` for `DRAW` is now the positive `units_delta` (`domain.py:138`), not its negation.
- **Verdict:** PRD §3.9 already uniquely determines this. Three independent pins in the existing prose:
  1. PRD.md:220 — "the units delta is computed as the posting's **absolute** `amount_cents` divided by the current `unit_value_cents`" — the delta is non-negative by definition.
  2. PRD.md:222 — the ledger records "signed `amount_cents`, computed `units` (zero for investment returns)" — "signed" attaches only to `amount_cents`; "computed `units`" can only refer to the absolute-based delta defined in the pinned step one; the parenthetical pins `INVESTMENT_RETURN` to zero.
  3. PRD.md:220 — "a `DRAW` **subtracts** its units delta" — a negative stored delta would grow `units_outstanding`, contradicting the same sentence; the aggregate is independently observable via `units_outstanding` in the fund serializer.

### Pre-edit verification (zero-edit case: enumeration proving no edit is needed)

Subject of the candidate edit area: the stored ledger `units` field and its sign convention. Every implementation path touching it was enumerated and read:

- `implementation/services/domain.py:114-116` — `units_delta = utils.round4(abs(amount_cents), fund["_unit_value_cents"])` computed only for `CONTRIBUTION`/`DRAW`.
- `implementation/services/domain.py:138` — sole write of the stored field: positive delta for `CONTRIBUTION`/`DRAW`, `Decimal("0.0000")` for `INVESTMENT_RETURN`.
- `implementation/services/domain.py:424` — sole read of the stored field (`txn_json` serializer, via `utils.num4`).
- `implementation/services/domain.py:117-124` — aggregate application: contribution adds delta, draw subtracts delta and `abs(amount)`, return adds signed amount — verbatim match to PRD §3.9 step two.
- `implementation/routes/endowment.py:107, 123, 169` — all three `post_ledger` callsites: contribution passes positive amount, return passes signed amount, draw passes `-d` (matching PRD.md:224 "carries an `amount_cents` equal to the negated draw amount").
- `implementation/services/domain.py:392-413` (`fund_json`) reads `units_outstanding`/`_unit_value_cents`, never the ledger field — consistent with PRD.md:220's "unit value reads null while `units_outstanding` is zero".

Auxiliary evidence: `test_suite/test_11_endowment_funds.py:499` asserts `draw["units"] == approx(1090.9091)` (positive) and its docstring quotes PRD §3.9 verbatim — the test is faithful to existing prose, confirming the bug was in the implementation, exactly as the step_7_diff recorded. No wording adjustment was needed for any enumerated path, so no edit was committed.

## Step 9: Complete PRD — 2026-08-14T05:12:00.000Z

Task complete. PRD_COMPLETED.md is written at `/home/ubuntu/github/CodingPRD/tasks/task_1620_conservation_easement_land_trust/workspace/PRD_COMPLETED.md`.

## Summary

**Source vs output**: PRD_FINALIZED.md 361 lines / 59,399 chars → PRD_COMPLETED.md 361 lines / 62,074 chars (char-delta **+2,675**; 23 lines revised in place, no lines added/removed, no new sections).

**Counts**: 22 ambiguity-pins, 2 mismatch-revisions (the §3.5 conditions edit contains one of each).

### Changes

- §2.2 — insert — ambiguity — `api_request_timestamp` reads the logical clock — implementation/response.py:14-18
- §2.3 — insert — ambiguity — non-integer/out-of-range `limit`, non-integer/negative `offset` → `ERR_INVALID_REQUEST` (400); `created_at` ties broken by insertion order — middleware.py:74-106
- §2.4 — insert — ambiguity — `created_at`/`updated_at` read from the logical clock — utils.py:22-26
- §2.5 — insert — ambiguity — clock sweep mutates an easement only when its posture actually flips between old/new clock date; easements already bumped by an escalation in the same sweep are not advanced again — services/domain.py:191-198
- §2.10 — insert — ambiguity — clock input parsing (date-only = midnight UTC; offset/naive normalized to UTC; unparseable → `ERR_INVALID_REQUEST`) and response shape `data.current_utc` — routes/clock.py:14-24
- §3.1 — insert — ambiguity — landowner list filters `easement_id`, `predecessor_landowner_id`, `status` — routes/landowners.py:63-73
- §3.1 — insert — ambiguity — baseline request-revision requires string `revision_notes`, else `ERR_INVALID_REQUEST` — routes/baselines.py:123-126
- §3.1 — insert — ambiguity — baseline list filters `easement_id`, `status` — routes/baselines.py:68-78
- §3.1 — insert — ambiguity — easement list filters `current_landowner_id`, `status`, `posture` — routes/easements.py:67-83
- §3.3 — insert — ambiguity — supplied `monitoring_visit_id` must be `COMPLETED`, else `ERR_INVALID_REQUEST` — routes/violations.py:60-61
- §3.3 — insert — ambiguity — violation list filters `easement_id`, `monitoring_visit_id`, `status`, `severity` — routes/violations.py:97-105
- §3.4 — insert — ambiguity — execute requires `agreement_terms` + `remediation_cost_cents`, else `ERR_INVALID_REQUEST` — routes/enforcement.py:44-52
- §3.4 — insert — ambiguity — renegotiate requires fresh terms/cost (else `ERR_INVALID_REQUEST`) and retains `breach_notes` — routes/enforcement.py:99-119
- §3.4 — insert — ambiguity — enforcement list filters `violation_id`, `easement_id`, `status` — routes/enforcement.py:21-29
- §3.5 — insert — ambiguity — `use_type` not a matrix key → `ERR_INVALID_REQUEST` — routes/use_authorizations.py:47-48
- §3.5 — revise — mismatch — `conditions` validation softened from "array of condition strings" to impl's rule (non-array or empty rejected; elements not individually validated), plus pin that `conditions` stores null for `APPROVED`/`DENIED` — routes/use_authorizations.py:122-134
- §3.6 — insert — ambiguity — amendment request-revision requires `revision_notes`, else `ERR_INVALID_REQUEST` — routes/amendments.py:136-139
- §3.6 — insert — ambiguity — approval auto-deny sets both `status` and `decision` to `DENIED` — routes/amendments.py:184-188
- §3.6 — insert — ambiguity — amendment list filters `easement_id`, `status` — routes/amendments.py:94-102
- §3.7 — insert — ambiguity — no limit on concurrent in-flight succession notices per easement — routes/succession.py:23-85
- §3.8 — insert — ambiguity — negative `enhancement_value_cents` → `ERR_INVALID_REQUEST` — routes/appraisals.py:109-121
- §3.9 — insert — ambiguity — fund creation is not gated on a `RECORDED` easement; fund list filters `easement_id`, `status` — routes/endowment.py:30-90
- §3.9 — insert — ambiguity — transaction listing supports optional `txn_type` filter — routes/endowment.py:192-203
- §3.9 — insert — ambiguity — investment returns accept any integer incl. zero; non-draw ledger entries carry null `purpose`/bucket fields — routes/endowment.py:114-125, services/domain.py:138-142
- §4 — revise — mismatch — transactions path placeholder `{id}` → `{endowmentFundId}` (matches route and §2.9 404 name) — routes/endowment.py:192

**Deliberately not pinned**: framework-level `ERR_NOT_FOUND`/`ERR_INTERNAL` handlers (app.py:60-70, outside the specified surface), and clock monotonicity (impl permits backward sets; no rule invented).

All other implementation behavior — every endpoint's validation order vs the §2.9 pipeline, all state machines, the materiality/waterfall/carryover/unitization formulas, month-end clamping, OCC semantics, SoD pairs, escalation cascades, envelope shape — was verified already uniquely pinned by PRD_FINALIZED.md.
