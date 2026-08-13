# Worklog — task_1478_jobsite_safety_program_regulatory

## Step 1: Create Task Directory — 2026-08-13T11:22:00.000Z

Task directory `tasks/task_1478_jobsite_safety_program_regulatory/` and `workspace/` pre-assigned by the pipeline invoker (treated as DONE; no index scan performed).

## Step 2: Generate Scaffold — 2026-08-13T12:26:00.000Z

Done. SCAFFOLD_CORNER_DESIGN.yaml is now written, and the full three-file package passes the skill's linter cleanly.

## Confirmation

All three required artifacts exist at `/home/ubuntu/github/CodingPRD/tasks/task_1478_jobsite_safety_program_regulatory/`:

- `SCAFFOLD.yaml` — §1.0–§1.7 only (verified: no `scaffold_difficulty_design` / `scaffold_corner_design` keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top-level key `scaffold_difficulty_design`
- `SCAFFOLD_CORNER_DESIGN.yaml` — single top-level key `scaffold_corner_design`

## Counts

**SCAFFOLD.yaml:** 12 entities, 11 state machines (Project has no machine — its `safety_posture` is a computed gate), 8 calculations, 58 endpoints (incl. `POST /safety/_clock/set_current_utc` with the mandated `2026-08-01T00:00:00Z` startup default), 43 error codes, 5 roles (SubcontractorRep is `entity_backed:Subcontractor`; others opaque), 1 OCC concurrency rule (`safety-plan-activate-stale-project` on `Project.version`, 412 `ERR_STALE_VERSION`), validations in 9 priority tiers, fixed response envelope verbatim.

**SCAFFOLD_DIFFICULTY_DESIGN.yaml:** 9 rules × 2 = **18 instances** — dual-variant (incident rates final/provisional vs subcontractor score realtime/period_90d), combinatorial (tiered+doubling score [mode a] vs round-components-then-subtract rate spread [mode b], pinned at 2.7/1.3/1.4), non-linear machines (Deficiency reject-reopen cycle vs DrugTestRecord POSITIVE/NEGATIVE fork), depth-3 cascades from different triggers (CRITICAL incident freeze vs POSITIVE drug test), priority conflicts (state>safety vs referential>temporal), boundaries (32h drug-test window inclusive vs strict <80 demote), cross-entity gates (Permit→JHA, Worker→Certificate), overlap semantics (half-open excavation adjacency vs closed-interval crew), invariants (issued-permit count, score-point refund).

**SCAFFOLD_CORNER_DESIGN.yaml:** **47 instances total** — 41 active with full test_recipes across all 9 guide sections (entities 4, state_machines 4, calculations 3, validations 13, endpoints 2, errors 9, rbac 3, cross_cutting_layers 2, consistency_model 1) + 6 `excluded_because:` stubs citing §1.8 instances.

## Verification

Lint verdict (verbatim):
```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```
(558 calls scanned across 18 + 41 instances; 58 endpoints; 12 entities.) Additionally verified mechanically: all 65 instance names unique across both files, every `grounds:` ref resolves to a declared §1.1–§1.7 element, and no forbidden concurrency vocabulary in any file. No sibling task directories were read at any point.

## Step 3: Copy Shared Files — 2026-08-13T12:28:30.000Z

Copied `./INSTRUCTION.md` → `tasks/task_1478_jobsite_safety_program_regulatory/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-13T12:45:00.000Z

PRD generation complete. Output file: `tasks/task_1478_jobsite_safety_program_regulatory/workspace/PRD.md` (306 lines, ends at §5 with no audit footer).

**Document structure** (skeleton designed from the domain, not copied from the example):
- §1 Introduction — 2 paragraphs, framed around the contractor safety department's regulator-vs-field tension and the "derived, not declared" design center
- §2 Global Specifications — 12 subsections: RBAC (with per-role `identity` translation, including entity-backed `SubcontractorRep`), verbatim §2.2 response envelope, pagination, common resource properties, the logical clock + sweep ordering, project safety posture (with the pinned posture/permits evaluation order), the three-link enforcement cascade (worker → permit → JHA), segregation of duties, the 9-priority validation pipeline in prose, nested-resource/cross-project 404 rules, OCC (single endpoint: plan activation with `expected_project_version` → `ERR_STALE_VERSION` 412), and precision/rounding rules
- §3 Business Logic — 8 subsections organized by operational workflow: site setup/plans, workforce badging + certificates, huddles + JHAs, permits + the three temporal conflict rules, inspections + deficiency correction loop, incidents + OSHA recordability/rates, subcontractor scoring/standing/removal, drug-free workplace
- §4 Endpoint table — 58 rows (33 POST, 25 GET), 4 columns only
- §5 Error catalogue — 43 rows, 2 columns only

**Coverage**: 12 entities, 58 endpoints, 43 error IDs, 8 state machines (all transitions with preconditions/side-effects rendered in prose), 8 calculations (deficiency SLA 14/7/3/0 days, dual-variant compliance score with overdue doubling and NOT_SUB_FAULT refund, OSHA recordability, TRIR/DART with pinned round-then-spread order, posture state derivation, the three permit interval rules with half-open/60-minute-buffer/closed-interval distinctions, the 32-hour both-inclusive drug-test window, training clearance bar), 9 validation priorities in explicit order, 1 OCC rule, 5 roles.

**Notable design decisions**: constants embedded in context (200,000 OSHA base hours explained as ~100 full-time workers; "exactly 80 does not qualify" for DEMOTE vs inclusive RESTORE); scatter strategy puts posture rules in §2.6 with gates referenced from §3.2/3.4/3.5/3.6; the recurring three-link cascade defined once in §2.7 and re-entered from posture freeze, positive drug tests, and subcontractor removal; permit lifecycle parameters split across §3.4 paragraphs with conflict-rule semantics given three distinct named interval models.

**Hard Contract Reports**:
```
Field coverage check:
- entities[].fields: 73 required, 73 present, 0 missing
- endpoints[].request_body + query_params: 12 required, 12 present, 0 missing
- path params: 12 required, 12 present, 0 missing
- computed output fields (osha-summary, clock): 11 required, 11 present, 0 missing
Status: PASS

Rule coverage check:
- validations[] with priority: 9 checked, 9 expressed in prose (§2.9 ordered pipeline), 0 missing
- concurrency_rules[] OCC rejections: 1 checked, 1 expressed (activate + expected_project_version + ERR_STALE_VERSION 412, no race framing), 0 missing
- state_machines[].transitions: 33 checked, 33 fully expressed (from/to, preconditions + error_ids, side effects), 0 missing
- calculations[]: 8 checked, 8 fully expressed in precise prose (constants, thresholds, inclusivity, rounding order), 0 missing
- validations[] conditions: 9 checked, 9 matchable to error_ids in §2/§3 prose, 0 missing
- endpoints[].side_effects / applies_to: all expressed (cascades, counter/version mutations, scope enumerations), 0 missing
- entities[].fields[] structured content: defaults/initials/nullability reconstructible from prose, 0 missing
- sibling-branch symmetry: 6 groups checked (DEMOTE/RESTORE, CLOSED/REJECTED, NEGATIVE/POSITIVE, 3 expiry branches, 3 conflict rules, dual score variants), all equal density
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 487
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

§2.2 verified byte-identical to `section-2.2-response-structure.md`. All 43 error IDs appear in §2/§3 prose; all enum/state values appear backticked. The difficulty/corner design files were not opened; no sibling task directories were touched.

## Step 5: Generate Unit Tests — 2026-08-13T13:40:00.000Z

Generation complete. Summary:

## Test counts

**Queue A (Difficulty)** — 36 tests, 2 per instance, all 18 instances covered:
- dual_variant_calc: `incident_rate_provisional_vs_final` ×2, `subcontractor_score_realtime_vs_period` ×2
- combinatorial_formula: `score_tiered_overdue_doubling` ×2, `osha_rate_rounding_order_spread` ×2
- non_linear_state_machine: `deficiency_correction_reject_reopen_cycle` ×2, `drug_test_branching_fork_divergent_effects` ×2
- transitive_cascade: `critical_incident_freeze_cascade` ×2, `positive_drug_test_suspension_cascade` ×2
- priority_pair_validation_conflict: `permit_issue_state_vs_posture_priority` ×2, `permit_create_jha_vs_overlap_priority` ×2
- boundary_precision_check: `drug_test_window_exactly_32h_compliant` ×2, `score_threshold_exactly_80_demote_rejected` ×2
- cross_entity_state_dependency: `permit_create_requires_jha_approved` ×2, `worker_clear_requires_verified_cert` ×2
- resource_temporal_overlap: `excavation_adjacency_allowed_overlap_rejected` ×2, `crew_closed_interval_touching_conflicts` ×2
- compensating_invariant: `permit_issue_close_count_invariant` ×2, `score_deduction_refund_invariant` ×2

**Queue B (Corner)** — 41 tests, 1 per non-stub instance (entities 4, state_machines 4, calculations 3, validations 13, endpoints 2, errors 9, rbac 3, cross_cutting_layers 2, consistency_model 1). The 6 `excluded_because:` stubs were not translated; all 6 stub cross-references were verified to resolve to real difficulty instances.

**Total: 77 tests.**

## Per-file breakdown
- `test_01_projects_and_safety_plans.py` — 4 (defaults, project 404, revision_no, OCC stale-version activation)
- `test_02_worker_orientation_and_clearance.py` — 8 (conditional subcontractor field, orientation gate, training gate ×2, standing/posture clear gates, REMOVED lockdown, suspend-from-pending)
- `test_03_training_certificates.py` — 4 (verify-twice, expired verify, window overlap + touching renewal, expiry day granularity)
- `test_04_huddles_and_jhas.py` — 4 (conduct side effects, MISSED sweep, duplicate date, unconducted-huddle JHA gate)
- `test_05_permits.py` — 15 (close-from-REQUESTED, JHA gate ×2, excavation half-open ×2, crew closed-interval ×2, priority pairs ×4, frozen-posture issue block, count invariant ×2, manual-only reinstate)
- `test_06_inspections_and_deficiencies.py` — 8 (reject/reopen cycle ×2, SoD verify, verify-from-OPEN, DUE-inspection gate, rep ownership 403, IMMINENT_DANGER freeze, immediate consistency)
- `test_07_incidents_and_osha_summary.py` — 10 (near-miss not recordable, drug-test close gate, investigator SoD, skip-investigate rejection, freeze cascade ×2, final/provisional rates ×2, rounding order ×2)
- `test_08_subcontractor_scoring.py` — 10 (variant split ×2, overdue doubling ×2, demote at exactly 80 + just below, restore at exactly 80, remove-from-GOOD_STANDING, refund invariant ×2)
- `test_09_drug_tests.py` — 7 (32h exact/lower-bound compliant ×2, past-32h rejection + non-persistence, POSITIVE/NEGATIVE fork ×2, cascade ×2)
- `test_10_access_and_envelope.py` — 7 (missing/invalid auth headers, rep/Superintendent role denials, auditor read-only + auditor-only reads, worker/permit typed 404s, pagination envelope, worker filters)

## Instances skipped
None. All 59 non-stub instances passed the PRD-first two-condition filter. Two deliberate assertion scoping decisions (recorded here, not emitted as weakened placeholders): (1) `project_create_defaults_applied` asserts posture/counters/`current_active_plan_id` (PRD §3.1 verbatim) but omits the instance's `version == 1` sub-assertion, since the PRD never states the initial version value; (2) `huddle_missed_auto_transition_on_sweep` uses a clock advance to 2026-08-04T00:00:00Z instead of the recipe's 2026-08-03T12:00:00Z, so the flip is unambiguous under either reading of "later than one day after `huddle_date`".

## Infrastructure
`test_helpers/` contains all 9 specified modules: types (12 TypedDicts, all enums, 5 roles), api_client (64 endpoint methods over GenericApiClient), api_errors (43 error IDs + HTTP map registered via `set_error_http_status_map`), assertions (per-entity + posture invariants), factories (input-field-only payloads honoring the DIRECT/SUBCONTRACTOR and POST_INCIDENT conditional-field rules), constants (SLA days, severity deductions, 80 threshold, 32h window, 60-min buffer, 200k base hours), test_users (opaque-role constants + `make_subcontractor_rep_headers` entity-backed builder), fixtures (full composite chains including `setup_jobsite_with_issued_permit`, incident pipeline, deficiency lifecycle, resulted drug tests), and the barrel `__init__.py`.

## Verification
All 20 files compile, all modules import cleanly against the installed framework, 77/77 tests carry exactly one docstring-terminal `Design:` line resolving to a real instance, every docstring contains a ≥8-word verbatim PRD fragment (automated grep-normalized check, 0 failures), and no skip/xfail markers or scaffold references exist anywhere in the generated code.

## Step 6: Generate Implementation — 2026-08-13T13:40:00.000Z

Implementation complete and smoke-tested. Summary:

**Files** (all under `tasks/task_1478_jobsite_safety_program_regulatory/workspace/implementation/`):
- `start.sh` — guarded pip install (`import flask` check), `exec python3 app.py`, binds `0.0.0.0:$PORT` (default 10000)
- `requirements.txt` — flask
- `app.py` — Flask app factory, ApiError/404/405/500 handlers, route registration
- `db.py` — in-memory `Store` (12 entity dicts + logical clock defaulting to exactly `2026-08-01T00:00:00Z` + insertion seq); fresh per process, zero seeding
- `errors.py`, `helpers.py` — envelope (`meta.api_request_id/api_request_timestamp`, `response_type`, `data`; list pagination `limit/offset/total_count/has_more`, defaults 10/0 clamped to [1,100]/≥0), auth (`X-User-ID`/`X-User-Role`, 5 roles), priority-4 field validators, ISO parsing (second-precision datetimes, day-granularity dates)
- `services.py` — posture computation + FROZEN-transition cascade, 3-link enforcement chain, both compliance-score variants (realtime with OVERDUE doubling; period-90d with NOT_SUB_FAULT refund), training clearance, certificate window overlap (half-open on expiry edge), permit 3-rule conflict check (excavation half-open / hot-work 60-min buffer / crew closed-interval vs {ISSUED,SUSPENDED} only), clock sweep in pinned order, OSHA rates (round-half-up 1dp, spread from rounded components), serializers
- `routes/` — 13 blueprints

**Coverage**: 12/12 entities, 58/58 endpoints (including `POST /safety/_clock/set_current_utc` and `GET .../osha-summary`), all 43 catalog error IDs with exact HTTP statuses (incl. 412 `ERR_STALE_VERSION`, 422s), validation pipeline ordered auth → role(+SubcontractorRep ownership) → existence (left-to-right, cross-project FK = 404) → shape → state → safety gates → referential → temporal → constraint.

**Verified by smoke tests** (two batches, ~110 assertions all passing after correcting script-side artifacts): OCC activate/supersede, training gate (OSHA_30 for supervisors), cert overlap + renewal-edge, huddle uniqueness/conduct, permit conflict boundaries (adjacency allowed, 59-min hot-work conflict, crew touching conflict), deficiency SLA due_at, score thresholds (80 exact: DEMOTE fails/RESTORE passes), segregation of duties, drug-test 32h inclusive window, POSITIVE cascade, IMMINENT_DANGER freeze + submit-from-OPEN no-recompute, overdue boundary (strictly-greater), posture RESTRICTED lift on submit-from-OVERDUE, pagination meta, reboot state wipe.

**Boot confirmation**: `bash start.sh` boots cleanly and serves HTTP within ~2s on throwaway ports 24117–24119; restart returns empty lists and the default clock. Test servers were killed after verification.

## Step 7: Run Tests and Iterate — 2026-08-13T14:05:00.000Z

Clean 8-round parallel sweep achieved — 77/77 passed in every round. Exiting with the Summary block.

---

## Summary

**Iterations run:** 2 (initial sweep → 1 fix → verification sweep, all 8 rounds clean)

**Tests deleted:** None.

**Failing test (union across rounds 1–8):** `test_06_inspections_and_deficiencies.py::TestImminentDangerFreeze::test_imminent_danger_deficiency_freezes_project` — failed all 8 rounds with `AssertionError: IMMINENT_DANGER due_at must equal created_at: 2026-08-01T08:00:00Z != 2026-08-01T08:00:00.000Z`.

**Diagnosis:** PRD §3.5 covers the rule verbatim ("`IMMINENT_DANGER` is due immediately — `due_at` equals the creation timestamp itself"), but the test asserted **string** equality while the PRD pins different per-field formats: §2.4 mandates `created_at` "with three fractional digits" and §2.12 defaults all other timestamps (including `due_at`) to second precision. A faithful PRD-only implementer produces equal instants with unequal string renderings — the assertion mis-translated instant-equality into string-equality (STEP 2: test wrong, assertion layer).

**Fixes applied to `test_helpers/`:** None.

**Fixes applied to `test_suite/`:**
- `tasks/task_1478_jobsite_safety_program_regulatory/test_suite/test_06_inspections_and_deficiencies.py` — added a module-level `_parse_ts()` helper (ISO 8601 → aware datetime) and changed the `due_at == created_at` assertion in `test_imminent_danger_deficiency_freezes_project` to compare parsed instants instead of raw strings, with a comment citing §2.4/§2.12. All other assertions in the test (FROZEN posture, permit SUSPENDED with `POSTURE_FROZEN`, JHA `RE_REVIEW_REQUIRED`) were already passing and are unchanged. This is a coverage correction, not a weakening — the PRD-pinned instant equality is still asserted exactly.

**Fixes applied to `implementation/`:** None — the implementation's format behavior (`created_at`/`updated_at` with three fractional digits per §2.4, `due_at` at second precision per §2.12) was already PRD-faithful.

**Final state:** 8/8 rounds at 77 passed / 0 failed / 0 errors.

## Step 8: Finalize PRD — 2026-08-13T14:20:00.000Z

**Output:** `workspace/PRD_FINALIZED.md` created, byte-identical to `PRD.md`.

**Line counts / delta:** PRD.md = 306 lines; PRD_FINALIZED.md = 306 lines; 0% delta (verified with `diff -q`: IDENTICAL).

**Changes:** None — zero edits. This is the anticipated valid zero-edit outcome, reached by verification rather than assumption.

### Why zero edits

The `<step_7_diff>` contains exactly one item: a **test-suite-only fix** (string equality → parsed-instant equality in `test_06_inspections_and_deficiencies.py`). No implementation fix, no test_helpers fix, no deletions. Under the HARD SCOPE rule, a PRD edit is only licensed when a fix reveals PRD-silence or PRD-mismatch; this fix revealed neither — Step 7 diagnosed it as "test wrong, assertion layer" with the implementation already PRD-faithful. The subagent's own verification confirms that diagnosis.

### Verification performed (in lieu of per-edit search logs)

**(a) Subject:** per-field timestamp rendering formats vs. instant equality for an `IMMINENT_DANGER` deficiency's `due_at` vs `created_at`.

**(b) Implementation paths enumerated and read/grepped:**
- `implementation/helpers.py:31-43` — `wall_ts()` (envelope, three fractional digits), `fmt3()` (three fractional digits), `fmt_ts()` (second precision)
- `implementation/helpers.py:231-244` — `parse_dt()` truncates inputs to seconds (`replace(microsecond=0)`)
- `implementation/db.py:3-4, 35-37` — logical clock defaults to `2026-08-01T00:00:00Z` (microsecond=0); `now()` returns it
- `implementation/services.py:14-19` — `SEVERITY_SLA_DAYS["IMMINENT_DANGER"] = 0`
- `implementation/services.py:457-466` — `_common()` renders `created_at`/`updated_at` via `fmt3`
- `implementation/services.py:599-615` — `ser_deficiency` renders `due_at` via `fmt_ts` (line 607) → second precision
- `implementation/services.py:507, 522, 565, 590, 592, 625, 648-649, 664` — every other timestamp of record (`activated_at`, `orientation_completed_at`, `conducted_at`, `due_date`, `completed_at`, `occurred_at`, `work_start`, `work_end`, `collected_at`) also rendered via `fmt_ts`/`_dt_or_none` — uniformly second precision, matching the §2.12 default
- `implementation/routes/deficiencies.py:86` — `due_at = created_at + timedelta(days=0)` for IMMINENT_DANGER → identical instant
- `implementation/routes/deficiencies.py:203`, `services.py:358` — overdue flip/re-flip compare datetimes (instants), never strings
- `implementation/routes/clock.py:18` — `current_utc` rendered via `fmt_ts` (§2.12 default; no PRD statement otherwise)

**(c) Wording adjustment:** none — no edit was committed.

**PRD-side confirmation that behavior is already uniquely determined:**
- §2.4 (lines 79-80) explicitly pins `created_at`/`updated_at` to "three fractional digits" — the only resource-field override.
- §2.12 (line 117) pins the default: "Timestamps are ISO 8601 UTC with second precision unless stated otherwise; envelope timestamps use three fractional digits." `due_at` is never "stated otherwise," so it is second precision.
- §3.5 (line 161) pins the *value* rule — "`IMMINENT_DANGER` is due immediately — `due_at` equals the creation timestamp itself" — inside the SLA-computation sentence; it is a statement about the instant, not the wire format.
- §2.5 (line 87) reinforces instant semantics: "Time comparisons across the system use second-precision timestamps."

Combined, a PRD-only faithful implementer produces exactly what the implementation does: equal instants, unequal string renderings (`...T08:00:00.000Z` vs `...T08:00:00Z`). The subagent also considered and rejected adding a clarifying sentence to §3.5: it is not licensed by HARD SCOPE (no silence), and per the NO-NEW-MISMATCH RULE it risks implying string-identity or a format contrast at other instant-equality sites (§2.5 sweeps, §3.5 reject-re-flip) that the implementation does not exhibit.

## Step 9: Complete PRD — 2026-08-13T14:50:00.000Z

Task complete. `workspace/PRD_COMPLETED.md` produced.

**Source vs output:** `PRD_FINALIZED.md` 306 lines / 52,983 chars → `PRD_COMPLETED.md` 306 lines / 57,234 chars (**+4,251 chars, +0 lines** — all changes are in-paragraph inserts/revisions; no sections added).

**Counts:** 21 ambiguity-pins, 5 mismatch-revisions (26 edited paragraphs total).

**Changes** (section — insert|revise — ambiguity|mismatch — what changed — impl ref):

- §2.1 — insert — ambiguity — whitespace-only header values count as empty — `implementation/helpers.py:84-90`
- §2.1 — insert — ambiguity — SubcontractorRep on a nonexistent deficiency gets the 404, not 403 — `implementation/routes/deficiencies.py:129-141`
- §2.2 — insert — ambiguity — envelope `api_request_timestamp` comes from wall clock, not the logical clock — `implementation/helpers.py:31-33,46-48`
- §2.3 — insert — ambiguity — out-of-range `limit`/`offset` clamped (not rejected); non-integer → `ERR_INVALID_REQUEST` — `implementation/helpers.py:255-274`
- §2.3 — insert — ambiguity — `created_at` sort ties broken by creation (insertion) order — `implementation/helpers.py:277-284`
- §2.3 — insert — ambiguity — `has_more` = `offset + len(page) < total_count`; filters exact-match, conjunctive, unmatched enum filters yield empty page not error — `implementation/helpers.py:51-60,277-284`
- §2.4 — insert — ambiguity — `version` starts at 1 at creation — `implementation/services.py:672-683`
- §2.4 — insert — ambiguity — any undeclared body key (not just server-managed fields) → `ERR_INVALID_REQUEST` — `implementation/helpers.py:126-129`
- §2.5 — insert — ambiguity — clock may be set to any valid instant; no monotonicity check — `implementation/routes/clock.py:10-18`
- §2.6 — revise — mismatch — posture recompute trigger list narrowed: no recompute on submit-correction from `OPEN` or verify-reject without re-flip (was "whenever any deficiency changes status") — `implementation/routes/deficiencies.py:151-157,203-207`
- §2.9 — insert — ambiguity — non-object/malformed/absent JSON body treated as empty object — `implementation/helpers.py:119-123`
- §3.1 — insert — ambiguity — both project counters are derived on read (ISSUED permits; OPEN/OVERDUE/CORRECTION_SUBMITTED deficiencies); counter changes alone never bump project version — `implementation/services.py:469-496`
- §3.1 — insert — ambiguity — plan activation checks DRAFT state before the OCC version comparison — `implementation/routes/plans.py:83-93`
- §3.2 — revise — mismatch — clearance condition order changed from training→standing→posture to training→posture→standing per §2.9 priorities — `implementation/routes/workers.py:145-168`
- §3.2 — insert — ambiguity — named `ERR_WORKER_INVALID_STATE` for suspend from non-ORIENTED/CLEARED and reinstate from non-SUSPENDED — `implementation/routes/workers.py:181-186,202-205`
- §3.3 — revise — mismatch — huddle conduct: unresolvable/cross-project attendee id → `ERR_WORKER_NOT_FOUND` 404 (was lumped under `ERR_WORKER_NOT_CLEARED`); only wrong-status → `ERR_WORKER_NOT_CLEARED` — `implementation/routes/huddles.py:90-121`
- §3.4 — revise — mismatch — issuance/reinstatement gauntlet order: state→posture→JHA→crew→temporal (prose previously listed temporal before crew) — `implementation/routes/permits.py:164-182`
- §3.4 — revise — mismatch — permit close `completion_notes` accepted but not persisted (was "recording") — `implementation/routes/permits.py:202-214`, `implementation/services.py:642-655`
- §3.5 — insert — ambiguity — inspection `due_date` is a full second-precision ISO 8601 timestamp, not a calendar date, and serialized as such — `implementation/routes/inspections.py:41`, `implementation/services.py:590`
- §3.5 — revise — mismatch — inspection complete: `findings_summary` optional; omitted → remains empty string — `implementation/routes/inspections.py:84-96`
- §3.5 — revise — mismatch — submit-correction rationale corrected: no recompute from `OPEN` even though CORRECTION_SUBMITTED no longer counts under the §2.6 formula (old rationale "still counts as open" contradicted the formula; counter behavior retained) — `implementation/routes/deficiencies.py:151-157`
- §3.5 — insert — ambiguity — verify `notes` accepted but not persisted — `implementation/routes/deficiencies.py:178`
- §3.5 — insert — ambiguity — verify requires source state `CORRECTION_SUBMITTED` (else `ERR_DEFICIENCY_INVALID_STATE`); verify-close bumps project version by exactly 1 even with a simultaneous posture change — `implementation/routes/deficiencies.py:180-185,198-200`
- §3.6 — insert — ambiguity — incident creation defaults: `investigation_notes` "", five determination flags false/0 — `implementation/routes/incidents.py:90-99`
- §3.6 — insert — ambiguity — determination requires `UNDER_INVESTIGATION` and close requires `DETERMINATION_MADE`, else `ERR_INCIDENT_INVALID_STATE` — `implementation/routes/incidents.py:167-172,199-204`
- §3.6 — insert — ambiguity — OSHA summary `year` is a required integer query param; missing/non-integer → `ERR_INVALID_REQUEST` — `implementation/routes/projects.py:64-70`
- §3.7 — insert — ambiguity — trailing-90-day score window inclusive at both bounds — `implementation/services.py:260-273`
- §3.7 — insert — ambiguity — removal `reason` required but not persisted; removal leaves workers' `suspension_reason` unchanged — `implementation/routes/subcontractors.py:119-135`, `implementation/services.py:190-202`
- §3.8 — insert — ambiguity — positive result on a worker not in ORIENTED/CLEARED is recorded but fires no transition or cascade — `implementation/services.py:205-212`

No remaining PRD silence or mismatch found against `implementation/`: all 58 endpoints' roles match the §4 table, sweep order/thresholds (§2.5), posture formula and freeze cascade (§2.6), three-link cascade reasons (§2.7), SLA days, severity deductions, 25-point incident deduction, 80-thresholds, 60-minute hot-work buffer, 32-hour inclusive window, and the OSHA round-then-subtract rate order were already uniquely pinned and match the code.

## Post-Step-9 verification sweep — 2026-08-13T14:39:10.000Z

Step 7's final sweep results files were absent from `implementation/` (cleaned up after the subagent's verification), so the orchestrator re-ran the full 8-round parallel stability sweep after Step 9 completed. All 8 rounds: **77 passed / 0 failed / 0 errors / 0 skipped** (~99s per round, exit code 0). The 8 `results.{1..8}.json` artifacts are present in `workspace/implementation/`. No code or test changes were needed — the Step 9 PRD edits were prose-only and the implementation/test artifacts are unchanged since Step 7's clean exit.

Pipeline COMPLETE: Steps 1–9 all done; `workspace/PRD_COMPLETED.md` exists (306 lines, +4,251 chars over PRD.md).
