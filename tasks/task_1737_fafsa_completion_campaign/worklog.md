# Worklog — task_1737_fafsa_completion_campaign

## Step 1: Create Task Directory — 2026-08-14T12:12:00.000Z

Task directory `tasks/task_1737_fafsa_completion_campaign/` and its `workspace/` subdirectory were pre-created and pre-assigned by the pipeline launcher. Step 1 treated as DONE per launcher instructions; no index scan performed, no other task_* directory touched.

## Step 2: Generate Scaffold — 2026-08-14T13:20:00.000Z

Scaffold generation complete. All three artifacts written and the linter is clean.

**Files written**
- `/home/ubuntu/github/CodingPRD/tasks/task_1737_fafsa_completion_campaign/SCAFFOLD.yaml` — §1.0–§1.7 only (no difficulty/corner keys)
- `/home/ubuntu/github/CodingPRD/tasks/task_1737_fafsa_completion_campaign/SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top-level `scaffold_difficulty_design:`
- `/home/ubuntu/github/CodingPRD/tasks/task_1737_fafsa_completion_campaign/SCAFFOLD_CORNER_DESIGN.yaml` — single top-level `scaffold_corner_design:`

**Counts**
- 15 entities, 14 state machines, 11 calculations, 12 validation rows (priorities 1–10), 73 endpoints (incl. one test-driving `POST /_clock/set_current_utc` with the mandated 2026-08-01T00:00:00Z default), 66 error codes, 6 roles (all with `identity:`), 2 OCC concurrency rules
- **24 difficulty instances**: dual_variant_calc 2, combinatorial_formula 3 (modes a/b/c), non_linear_state_machine 3, transitive_cascade 2 (depth-3 + depth-2, distinct triggers), priority_pair_validation_conflict 3 (state/safety, referential/temporal, temporal/fiscal), boundary_precision_check 3 (match score / event capacity / k-anonymity threshold), cross_entity_state_dependency 3 (registration→event, check-in→event, case→checklist), resource_temporal_overlap 2 (staff half-open adjacency vs school 30-min venue buffer), compensating_invariant 3 (budget cents / staff hours / case count)
- **45 active corner instances + 4 excluded stubs** across all 9 claim-extraction sections; 913 recipe calls scanned

**Lint verdict (verbatim)**
```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

**Notable design decisions (harder-than-expert calibration)**
- Archetype: compliance/audit + event-sourcing blend — `AidRecord.current_status` is a projection over append-only `AidStatusEvent`s with stale-event non-regression and created_at tie-break; consent revocation cascades pause cases/decrement caseloads/cancel registrations, and re-grant resumes cases to `previous_status` while deliberately NOT restoring registrations (asymmetric compensation).
- SeniorRecord carries parallel state axes (match_status × fafsa_status); SupportCase and CompletionEvent are cyclic; checklist flips COMPLETE→IN_PROGRESS on special-circumstance regeneration (dependency flip to INDEPENDENT re-templates items with system auto-waive).
- Dual-variant calcs in different domains: report completion rate (SUBMISSION_BASED vs PROCESSED_BASED) and event staffing coverage (committed vs pipeline); nested-rounding order pinned (overall rate from unsuppressed totals, never averaged rounded rows — fixture pins 18.2 vs the naive 18.4); recognition tiers use self-referential percentile cutoffs with pinned rates→cutoffs→tiers evaluation order.
- Privacy: consent-scoped field masking on reads, k-anonymity row suppression with strict-`<` threshold, configurable per-campaign thresholds (conditional-feature-flag corner).
- OCC on SeniorRecord.version (match-link create) and Campaign.version (report publish), both passing the serial-observability filter; all `expected_*_version` inputs are `${var}`-bound.
- Flat topology under `/fafsa` (per skill diversity guidance); SchoolCoordinator is `entity_backed:School` giving scoped-tenancy 403s; peer roles segregate data import (DataImporter) from match review (MatchReviewer) and case work (Specialist).

## Step 3: Copy Shared Files — 2026-08-14T13:21:00.000Z

Copied `./INSTRUCTION.md` to `tasks/task_1737_fafsa_completion_campaign/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-14T13:35:00.000Z

PRD generation complete. Summary below.

**Output**: `/home/ubuntu/github/CodingPRD/tasks/task_1737_fafsa_completion_campaign/workspace/PRD.md` — 388 lines.

**Section list**
- §1 Introduction (2 paragraphs, pain-point/business-context angle)
- §2 Global Specifications: 2.1 RBAC (all six roles with per-role `identity:` translations — `SchoolCoordinator` entity-backed by `School`, `StaffMember`/`Specialist` entity-backed by `StaffProfile`, the other three opaque), 2.2 Response Structure (verbatim fixed block), 2.3 Pagination (`limit` 10/1/100, `offset` 0, `created_at` ascending, meta fields), 2.4 Common Resource Properties (incl. the `AidStatusEvent` exception: only `id`/`created_at`, no `updated_at`/`version`), 2.5 Logical Campaign Clock (startup default `2026-08-01T00:00:00Z`, all four clock-driven transition families), 2.6 Consent-Gated Privacy (visibility rule + four-field masking quartet + scope-to-capability map), 2.7 Precision & Monetary Conventions, 2.8 OCC (both rules, explicit field + `ERR_STALE_VERSION`/412, no race framing), 2.9 Validation Precedence (10-level ordered list with error families), 2.10 Cascading Consistency (version/updated_at on cascade mutations, exact round-trip invariants, left-to-right path validation)
- §3 Business Logic, 10 subsections organized by pipeline stage: 3.1 campaign/deadline calendar + close cascade, 3.2 schools/staff registry + OVERLOADED/SUSPENDED threshold machines, 3.3 senior-list loading + aid-record import, 3.4 status projection + deadline classification + verification/auto-resolve cascades, 3.5 match scoring/bands/link decisions, 3.6 consent lifecycle cascades (asymmetric regrant), 3.7 events: publish gate, dual-variant `staffing_coverage`, budget ledger, 3.8 assignments + registrations, 3.9 checklists + polymorphic case resolution + regeneration, 3.10 reporting, k-anonymity suppression, recognition tiers
- §4 Endpoint table (73 rows, 4 columns only) — §5 Error catalogue (66 rows, 2 columns only)

**Hard-contract reports**
- Contract 1 (field coverage): entities[].fields 79/79 present; endpoint input/output ids 61/61 present (incl. `to_iso8601`, `now`, `result`, `specialist_id`, `initial_status`, both `expected_*_version` OCC fields); query params 15/15 present (incl. `subgroup_tag`). PASS
- Contract 2 (rule coverage): validation priority 1–10 expressed as explicit ordered prose in §2.9; both OCC rules expressed with endpoint framing + field + error id; all state-machine transitions expressed (incl. symmetric sibling branches: escalate/resolve from both `IN_REVIEW` and `AWAITING_FAMILY`/`ESCALATED`, pause from four states, invalidate from `CONFIRMED`/`AUTO_CONFIRMED`); all 10 calculations expressed as reconstructible prose (score weights 0.40/0.35/0.15/0.10, `rate` = round-half-up of completed/eligible × 1000 ÷ 10, nearest-rank ceil cutoffs at 0.70/0.40, day-granularity deadline classes, half-open overlap + exactly-30-min venue buffer allowed, strict less-than suppression with equality surviving, totals-from-unsuppressed pinning); every error id appears in §2/§3 prose. One defect found and fixed during verification: the `ERR_EVENT_FULL` capacity check was reworded to match the scaffold's `REGISTERED count >= capacity` semantics (last open seat succeeds). PASS
- Contract 3 (§3 path purity): 629 backtick tokens scanned in §3; 0 paths, 0 bare HTTP methods, 0 method+path combos. PASS

**Notable coverage decisions**
- The `AidStatusEvent` `common_fields: false` exception is called out explicitly in §2.4.
- Checklist template keying is stated as: `INDEPENDENT` → `INDEPENDENT_STANDARD`; `DEPENDENT`/`PENDING_REVIEW` → `DEPENDENT_STANDARD` (scaffold lists only two templates; this is the only consistent reading with the regeneration rule).
- The withheld files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were never opened; all content derives solely from `SCAFFOLD.yaml` and the skill spec.
- `ERR_BUDGET_EXCEEDED` carries HTTP 402 and both constraint-family 422s (`ERR_CROSS_CAMPAIGN_REFERENCE`, `ERR_ITEM_NOT_WAIVABLE`) are noted with their statuses in §3 prose; §5 maps all 66 ids.

## Step 5: Generate Unit Tests — 2026-08-14T14:25:00.000Z

Done. Everything is generated, audited, and smoke-verified against the live implementation.

**Files written** (22 total, all under `/home/ubuntu/github/CodingPRD/tasks/task_1737_fafsa_completion_campaign/`):

- `test_helpers/` (9): `types.py` (15 entity TypedDicts — `AidStatusEvent` correctly omits `updated_at`/`version` per the append-only rule), `api_client.py` (52 endpoint methods), `api_errors.py` (64 error IDs + HTTP map registered with the framework), `assertions.py`, `factories.py`, `constants.py`, `test_users.py` (shared constants for opaque roles + mandatory `make_*_headers` builders for the three entity-backed roles), `fixtures.py` (~30 composite helpers incl. `setup_dual_variant_scenario`, `setup_language_rate_scenario`, `setup_recognition_scenario`, `setup_verification_case`), `__init__.py` barrel.
- `test_suite/`: `conftest.py` + 12 numbered test files organized by concern (lifecycle, intake/envelope, matching, projection/deadlines, consent, checklists, cases, events/budget, staffing, registrations, reporting/recognition, security/precedence).

**Test counts**: 94 tests total — Queue A: 48 tests, all 24 difficulty instances at ≥2 each. Queue B: 46 tests, all 45 non-stub corner instances at ≥1 each. Every docstring ends with exactly one `Design:` line resolving to a real instance; the 4 `excluded_because:` stubs were not translated and their difficulty-instance pointers all resolve.

**Instances skipped**: none. One partial narrowing: `campaign_create_applies_threshold_defaults` drops the recipe's `version == 1` assertion — the PRD says version "starts at its initial value on creation" without pinning 1 vs 0, so it fails unique-derivability; all other asserts (six tuning defaults, DRAFT, zero budget counters, balance == total) are kept.

**Notable coverage decisions**:
- Two instances (`immediate_read_after_write_consistency`, `match_confirm_checklist_generation_depth2`) had recipes asserting unmasked `fafsa_status`/`current_match_link_id` without granting consent — which contradicts PRD §2.6 masking. I added a STATUS_DETAIL consent to their setups; the asserted cascade/consistency claims are unchanged.
- The three priority-pair instances each became: (1) the conflict test asserting the PRD §2.9-ordered winner, and (2) an isolated test proving the losing error fires alone — PRD §2.9's explicit fixed order makes both uniquely derivable.
- `specialist_selector_empty_pool_then_manual_assign` asserts `ERR_CASE_UNASSIGNED` on accept-with-null-assignee; PRD §3.9 pins that error's trigger, and an ownership-first reading would make it unreachable, so the test is kept.

**Verification performed**: py_compile + pyflakes clean (this caught and fixed one real bug — a missing `create_school_payload` import in fixtures.py); tag audit 94/94; verbatim citation audit — all 146 quoted segments ≥8 words grep literally in PRD.md (fixed ~30 punctuation/ellipsis drifts); pytest collects 94; live smoke against the running implementation (per-test server restart): 24 representative tests all pass, including the heaviest fixtures (16-senior recognition scenario, 11-senior rounding scenario, no-show contagion, pause/resume round-trip, both OCC paths, selector ranking, venue buffer, both remaining priority pairs).

## Step 6: Generate Implementation — 2026-08-14T14:25:00.000Z

The implementation is complete and verified. Both fresh boots come up clean with an empty store and respond within ~1.5 seconds.

**Files written:**
- `start.sh` — guarded launcher (`pip install` only if flask missing; `exec python3 app.py`; `0.0.0.0:$PORT`, default 10000)
- `requirements.txt` — flask>=3,<4
- `app.py` — Flask entry, error handlers, blueprint registration
- `db.py` — in-memory store (15 collections, empty on boot, logical clock default `2026-08-01T00:00:00Z`), `make_common`/`touch` helpers
- `errors.py` — full error catalog (60 IDs) with HTTP statuses
- `response.py` — envelope helpers matching scaffold §1.0 exactly (`meta.api_request_id/api_request_timestamp`, `response_type`, `data`; pagination fields in meta)
- `middleware.py` — `X-User-ID`/`X-User-Role` auth, 6-role RBAC, school-scope + ownership checks
- `dates.py` / `validate.py` — ISO 8601 parsing (datetime/date), request-shape validation, pagination (limit default 10, min 1, max 100)
- `routes/campaigns.py`, `routes/seniors.py`, `routes/events.py`, `routes/cases.py` — thin route handlers
- `services/core.py` — all cross-entity logic (~1100 lines)

**Endpoint count:** 61 (1 clock + 60 under `/fafsa`), all from the scaffold §1.5 table.

**State machines implemented (11):** Campaign (DRAFT/OPEN/STATE_GRACE/CLOSED with clock-driven transitions and close cascade), School (INVITED/ENROLLED/SUSPENDED), StaffProfile (ACTIVE/OVERLOADED/SUSPENDED with threshold flips + suspension contagion), SeniorRecord (parallel match_status × fafsa_status axes), AidRecord (event-sourced projection with backdated-event retention), MatchLink (SUGGESTED/AUTO_CONFIRMED/CONFIRMED/REJECTED/AUTO_REJECTED/INVALIDATED), ConsentRecord (GRANTED/REVOKED/EXPIRED with asymmetric pause/resume cascade), CompletionEvent (DRAFT/PUBLISHED/IN_PROGRESS/COMPLETED/CANCELLED), StaffAssignment (7 states), EventRegistration, DocumentChecklist + ChecklistItem (derived status), SupportCase (8 states incl. PAUSED with previous_status), CompletionReport (GENERATED/PUBLISHED/SUPERSEDED).

**Calculations implemented (10):** match_score (exact Decimal tenths, weights 0.40/0.35/0.15/0.10), completion_rate (dual-variant SUBMISSION_BASED/PROCESSED_BASED, round-half-up 1dp, k-anonymity strict-`<` suppression with unsuppressed totals), deadline_classification (day-granularity, inclusive upper bounds), event_staffing_coverage (committed + pipeline variants, 2dp), recognition_tier (pinned rates→cutoffs→tiers order, nearest-rank ceil percentiles 70/40, inclusive boundaries), subgroup_suppression, specialist_selection (language DESC, caseload ASC, created_at ASC), staff_hours_accrual (2dp round-half-up, exact compensation), caseload_invariant, budget_ledger (integer cents, exact publish/cancel round-trip), overlap_checks (half-open staff double-booking; 30-min venue buffer with exactly-30 allowed).

**Storage:** in-memory dicts keyed by UUID; no seeding; every entity created via the API. Cascade mutations bump `version` and refresh `updated_at`; `AidStatusEvent` is the sole append-only exception (no `updated_at`/`version`).

**Notable design decisions:**
- OCC on `expected_senior_record_version` (match-link create) and `expected_campaign_version` (report publish), evaluated with existence/state before business rules per PRD §2.9 — verified to return 412 before the link-existence 409.
- Consent-gated masking of the aid-status quartet (`fafsa_status`, `submitted_at`, `deadline_classification`, `current_match_link_id`) applied at the serialization layer, so it covers both list and detail reads for all roles.
- Coordinator scoping enforced both on writes (school_id == X-User-ID) and on list reads (filtered to own school); StaffMember/Specialist ownership on accept/decline and case actions.
- Verified via five live smoke suites (all passing) covering: envelope shape, auth/role/scope, OCC, match bands + confirm/reject/invalidate, checklist generation + archival, verification auto-case (OPEN vs PAUSED), consent revoke/regrant caseload round-trip, specialist selector + OVERLOADED flip + reassign, INDEPENDENT_CONFIRMED checklist regeneration, budget commit/release/spend, venue buffer boundary, double-booking (touching endpoints allowed), no-show suspension contagion, clock close cascade leaving IN_PROGRESS events standing, report suppression/tiers/supersede, pagination, and empty-store fresh boots through `bash start.sh` on both default and custom ports.

## Step 7: Test-Iterate Loop — 2026-08-14T15:05:00.000Z

First 8-round parallel stability sweep (`prd-bench-local-run --isolation per-test-server`, 8 concurrent rounds, 94 tests each) came back clean on the first iteration: every round reported `passed=94/94, failed=0, errors=0` (~123–124 s per round under 8× load). No flaky failures across the union of all 8 rounds, so no fixes or deletions were required.

- Iterations run: 1
- Tests deleted: none
- test_helpers/ fixes: none
- implementation/ fixes: none

## Step 8: Finalize PRD — 2026-08-14T15:06:00.000Z

SKIPPED per the skip condition: Step 7 exited on the first 8-round sweep with 0 deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes. `PRD.md` already determined every behavior the implementation exhibits, so no `PRD_FINALIZED.md` was produced; Step 9 will read from `PRD.md` directly.

## Step 9: Complete PRD — 2026-08-14T15:30:00.000Z

Produced `/home/ubuntu/github/CodingPRD/tasks/task_1737_fafsa_completion_campaign/workspace/PRD_COMPLETED.md` as a minimal patch over `PRD.md` (copied, then edited in place; no new sections, all changes are in-paragraph inserts/revisions).

**Size**: PRD.md 388 lines / 61,886 chars → PRD_COMPLETED.md 394 lines / 68,896 chars (char-delta +6,954; 62 changed diff lines).

**Counts**: 32 ambiguity-pins, 6 mismatch-revisions, 8 cross-reference corrections.

**Changes** (each: section — insert|revise — ambiguity|mismatch — what — impl evidence):

- §2.1 — insert — ambiguity — read-scoping rules: coordinator list/detail scoping for seniors/consents/checklists/registrations/case-lists with `ERR_SCHOOL_SCOPE_VIOLATION` on foreign single reads; StaffMember/Specialist self-scoped assignment lists; Specialist self-scoped case lists; unscoped single assignment/case reads — middleware.py:44-59; routes/seniors.py:88-107,438-458; routes/cases.py:31-63,205-230; routes/events.py:280-297,442-465
- §2.2 — insert — ambiguity — envelope `api_request_timestamp` is wall clock, not the logical clock; undefined path/method → `ERR_INVALID_REQUEST` at 404/405 — response.py:8,19,49; app.py:25-31
- §2.3 — insert — ambiguity — non-integer/out-of-range `limit`/`offset` → `ERR_INVALID_REQUEST`, offset ≥ 0; `created_at` ties broken by creation order — validate.py:134-156; services/core.py:1096-1100
- §2.4 — revise — ambiguity — `version` starts at 1 — db.py:53-61
- §2.5 — insert — ambiguity — clock set unconditionally (backward allowed, never reverses); fixed per-call transition order consents → campaigns (close cascade) → events, so a same-call close cancels a due event while still `PUBLISHED` — services/core.py:515-557
- §2.6 — insert — ambiguity — list filters match stored values before masking — routes/seniors.py:94-95 + services/core.py:1087-1090
- §2.7 — revise — mismatch — interval arithmetic at exact parsed precision (not "minute granularity"); added: no non-negativity on monetary fields; datetime parser accepts `T`/space separator and `Z`/numeric offsets normalized to UTC — services/core.py:307-353; dates.py:12-45; validate.py:57-67
- §2.9 — insert — ambiguity — required strings must be non-empty (step 3); not-found for the governing resource precedes scope/ownership errors; endpoint-named check orders override the generic numbering — validate.py:33-41; routes passim
- §3.1 — revise — mismatch — "Five tuning knobs" → "Six" (six listed and implemented); knob minimums pinned (`min_subgroup_size`≥1, `max_caseload`≥0, `no_show_limit`≥1, `min_recognition_seniors`≥0; thresholds any number; `total_budget_cents` any integer) — routes/campaigns.py:43-58
- §3.1 — revise — mismatch — "a `CLOSED` campaign blocks all child writes" replaced: only the named gated set (school enrollment/reinstatement, senior loading, event creation/publication, report generation/publication) is campaign-gated; consent/match/checklist/case/aid-record writes carry no campaign gate; close cascade clears `previous_status` to null and only active-status cases decrement — routes (no campaign checks outside the gated set); services/core.py:493-508
- §3.2 — insert — ambiguity — school/staff creation require only campaign existence, any state; invalid capability → `ERR_INVALID_REQUEST`; languages stored unvalidated; background-check has no state precondition; suspension carries no campaign gate — routes/campaigns.py:133,228-236,279-289,188-201
- §3.3 — insert — ambiguity — senior-create gate errors named (`ERR_SCHOOL_NOT_ENROLLED`, `ERR_CAMPAIGN_NOT_OPEN`); aid-record `dob`/`effective_date` are ISO dates, import allowed in any campaign state; status events list `effective_date` asc, ties by `created_at` — routes/seniors.py:46-49,128-137,231-232
- §3.4 — insert — ambiguity — a status event repeating the senior's current status mutates nothing — services/core.py:822-825
- §3.5 — insert — ambiguity — one-non-terminal-link check evaluated before cross-campaign check — routes/seniors.py:259-267
- §3.5 — revise — mismatch — senior `version` bump on link creation: +1 for `AUTO_REJECTED`, +2 for `SUGGESTED`/`AUTO_CONFIRMED` (PRD said "by one") — routes/seniors.py:296-303; services/core.py:899
- §3.5 — insert — ambiguity — auto-confirm fires the verification cascade only when the initial status differs from the senior's prior status — services/core.py:901
- §3.6 — insert — ambiguity — empty/unknown scopes → `ERR_INVALID_REQUEST`; a fresh grant that flips visibility to `NORMAL` fires the resume half of the regrant cascade (registrations stay cancelled) — routes/seniors.py:399-403,422-426
- §3.7 — insert — ambiguity — event-create gate errors named; `required_expert_count` ≥ 0; `supported_languages` may be empty — routes/events.py:38-51
- §3.7 — revise — ambiguity — publish has six preconditions, adding campaign `OPEN`/`STATE_GRACE` (`ERR_CAMPAIGN_NOT_OPEN`) evaluated first — routes/events.py:110-129
- §3.8 — insert — ambiguity — assignment-create against a non-`DRAFT`/`PUBLISHED` event → `ERR_EVENT_NOT_CANCELLABLE`; check order pinned: event state → cross-campaign → capability → duplicate → double-booking — routes/events.py:232-255
- §3.9 — insert — ambiguity — manual case creation also starts `PAUSED` (`previous_status` `OPEN`, not counted toward caseload) when the senior lacks `STATUS_DETAIL` consent — services/core.py:723-749
- §3.9 — insert — ambiguity — `SPECIAL_CIRCUMSTANCE` opening moves only `DEPENDENT` → `PENDING_REVIEW` — routes/cases.py:189-191
- §3.9 — insert — ambiguity — selector `created_at` ties broken by creation order — services/core.py:719
- §3.9 — insert — ambiguity — assign has no case-state precondition; counters shift only for active-status cases — routes/cases.py:233-254
- §3.9 — insert — ambiguity — case-action check order: state (`ERR_CASE_NOT_ACTIONABLE`) → assignee presence (`ERR_CASE_UNASSIGNED`) → ownership — routes/cases.py:257-281,305-316
- §3.9 — insert — ambiguity — resolve against a senior with no non-archived checklist → `ERR_CHECKLIST_NOT_COMPLETE`; `INDEPENDENT_CONFIRMED` regeneration is a no-op when no checklist exists — routes/cases.py:321-327; services/core.py:667-675
- §3.10 — insert — ambiguity — `SCHOOL` row key is `id` + single space + `name`; surviving rows ordered by `dimension` then `key` ascending; zero-eligible schools never enter the recognition pool — services/core.py:982,986,1031-1035
- §4 table — revise — mismatch — completion-report list/get roles: five roles excluding `StaffMember` (PRD said "All six roles") — routes/cases.py:16,391-412
- Cross-reference corrections (mismatch-class, 8 one-token fixes): §2.5 revocation ref §3.5→§3.6; §3.1 matching-bands ref §3.3→§3.5; §3.1 event-cancel cascade ref §3.6→§3.7; §3.1 budget-maintenance ref §3.6→§3.7; §3.2 suspend-cascade ref §3.6→§3.7; §3.2 recognition ref §3.9→§3.10; §3.4 selector ref §3.8→§3.9; §3.5 checklist-generation ref §3.7→§3.9

Key findings worth flagging: the three substantive PRD-vs-impl conflicts were the senior version bump on link creation (+2/+2/+1, not +1), report reads excluding `StaffMember`, and the blanket "CLOSED blocks all child writes" claim (impl gates only six named write families); plus three localized validation-precedence deviations from §2.9 (match-link: duplicate-before-cross-campaign; assignment-create: capability/duplicate-before-double-booking; case actions: state-before-ownership), each pinned with a scoped sentence rather than rewriting the global order.
