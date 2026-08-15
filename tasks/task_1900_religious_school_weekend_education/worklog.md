# Worklog — task_1900_religious_school_weekend_education

## Step 1: Create Task Directory — 2026-08-14T23:45:00.000Z

Task directory `tasks/task_1900_religious_school_weekend_education/` and `workspace/` pre-created by the pipeline launcher (Step 1 done outside this run; verified present and empty).

## Step 2: Generate Scaffold — 2026-08-15T00:38:10.000Z

All three scaffold artifacts are generated and lint-clean. Summary of the delivery:

**Files written** (in `/home/ubuntu/github/CodingPRD/tasks/task_1900_religious_school_weekend_education/`):
- `SCAFFOLD.yaml` — §1.0–§1.7 only (no `scaffold_difficulty_design`/`scaffold_corner_design` keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top-level key `scaffold_difficulty_design:`, 19 instances
- `SCAFFOLD_CORNER_DESIGN.yaml` — single top-level key `scaffold_corner_design:`, 46 instances (42 active + 4 `excluded_because` stubs)

**Design** (generated fresh; no sibling tasks were inspected):
- **Profile**: primary archetype `pricing_engine` (membership-linked tuition with sibling tiers, early-bird, assistance awards, late fees), secondary `quota_allocation` (grade+Hebrew-level placement into capacity-limited sections). Layers: dual-variant calculation, cascading side effects, rate/threshold triggers, optimistic concurrency. Flat topology, cyclic state machines, approval-chain role model, immediate consistency.
- **Surface**: 14 entities (SchoolYear, SecurityPlan, CalendarClosure, Family, Student, Teacher, Section, Enrollment, TuitionInvoice, Payment, AssistanceApplication, Session, Milestone, VolunteerCommitment), 60 endpoints, 30 error codes, 11 state machines, 8 calculations, 12-band validation ladder, 2 OCC concurrency rules (`enroll-stale-section`, `invoice-issue-stale-family`). Endpoint count deliberately exceeds the Expert guideline band (20–32): the scenario spans 8 subsystems and many GETs are lint-mandated FK reverse-reachability anchors.
- **Difficulty anchors**: dual-variant calcs in 3 domains (provisional-vs-final tuition with rank shift after sibling withdrawal; PERCENT_OF_NET vs FLAT_CAP aid awards; current vs projected attendance %), combinatorial modes (a) tiered+branch+rounding and (c) late-fee pre-fee snapshot ordering, transitive cascades (teacher separation → section unstaffing → session cancellation → milestone re-eval, depth 3+; volunteer entry void → commitment regression → milestone revert, depth 2), closed-vs-half-open interval overlap (closures vs room slots), money and seat-count compensating invariants, segregation-of-duties on assistance decide.
- **Determinism pins**: logical clock with mandatory default `2026-08-01T00:00:00Z`; all arithmetic assertions pre-computed in Python (e.g., 67062.5 → 67063 round_half_up trap; per-line-round-then-sum 127420 vs 127421; late fees 1081/1097; 80.0% inclusive milestone boundary); sibling-rank ties broken by request-arrival order, never by id.

**Verification**: `scaffold_lint.py` verdict — `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5` (60 endpoints, 14 entities, 19 + 46 instances, 947 calls scanned). Additional scripted audits passed: instance names unique across both design files (68 total), every error code triggered by at least one instance, all `grounds:` references resolve, no forbidden concurrency vocabulary. One self-found authoring bug fixed during replay: the early-bird boundary corner initially ignored sibling-rank interaction (assert now correctly pins rank1-at-deadline = 65250 vs 60356 one second earlier).

## Step 3: Copy Shared Files — 2026-08-15T00:38:10.000Z

Copied `./INSTRUCTION.md` to `tasks/task_1900_religious_school_weekend_education/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-15T00:49:00.000Z

PRD generated at `/home/ubuntu/github/CodingPRD/tasks/task_1900_religious_school_weekend_education/workspace/PRD.md`. The withheld difficulty/corner design files were not opened or referenced.

**Document design:** 2-paragraph introduction from the operational-pain-point angle; §2 with 10 subsections (roles/identity, verbatim response structure, pagination, resource properties & Family-specific version semantics, logical clock, money/precision, OCC, the 12-band validation priority, calendar interval semantics, safety/SoD); §3 with 8 subsections organized along the school-year timeline (year setup → faculty/sections → enrollment pricing → sessions/attendance/milestones → assistance → billing → withdrawals → volunteering/year-close); §4 with all 60 endpoints in a 4-column table; §5 with all 30 error codes in a 2-column table.

**Hard Contract Reports**

```
Field coverage check:
- entities[].fields: 81 required, 81 present, 0 missing
- endpoints[].request_body: 54 required, 54 present, 0 missing
- endpoints[].path_params: 2 required (id, entry_id), 2 present, 0 missing
- query filters (school_year_id, teacher_id, status, family_id, student_id, section_id, assistance_application_id): all present in §3 listing narratives
Status: PASS (two passes run; pass 1 surfaced a checker artifact from fenced JSON blocks, re-run with fences stripped confirmed full coverage)
```

```
Rule coverage check:
- validations[] priority bands: 12 checked, 12 expressed as an explicit ordered list in §2.8; milestone schedule's inner order (ELIGIBLE check before volunteer check) stated in §3.4
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write endpoint + expected_section_version/expected_family_version + ERR_STALE_VERSION 412, stale-read framing only) in §2.7
- state_machines[].transitions: 10 machines / all transitions checked and expressed (incl. PARTIALLY_PAID→VOID declared unreachable, staffing_status as independent derived dimension, SUBMITTED↔UNDER_REVIEW and TRACKING↔ELIGIBLE loops)
- calculations[]: 8 checked, 8 fully expressed in prose (tiered sibling/early-bird tuition with both rounding steps and arrival-order tie-break, round-per-line-then-sum invoice totals, both award variants, pre-fee-snapshot late fees without same-run compounding, weighted current/projected attendance, inclusive volunteer threshold, oldest-first payment waterfall, tiered withdrawal credit with exact boundary assignments)
- validations[] conditions: all 30 error IDs matchable to triggers in §2/§3 prose
- endpoints[].side_effects / applies_to: all expressed (3-hop teacher-separation cascade, closure cascade, year-close sweep, supersede rules, milestone reverts)
- entities[].fields[] structured content: defaults, nullables (approved_at, cancel_reason, withdrawn_at, withdrawal_credit_pct, award/review fields), denormalizations, and Family.version bump-only-on-balance-mutations all reconstructible
- sibling-branch symmetry: 8 parallel groups checked (VETTED vs HIRED separation, APPROVED vs DENIED decide, OPEN vs DEFAULTED waive, DEFAULTED vs FULFILLED close, current vs projected, provisional vs final, PERCENT_OF_NET vs FLAT_CAP, void regressions) — equal density
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 515
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Additionally verified: §2.2 is byte-identical to the canonical `section-2.2-response-structure.md`; all 60 scaffold endpoints appear in the §4 table with matching method/path/roles; no pseudocode operators or fuzzy/approximating words anywhere in the document.

## Step 5: Generate Unit Tests — 2026-08-15T01:10:00.000Z

Generation complete. Summary of what was produced for task_1900_religious_school_weekend_education:

## Stage 1 — `test_helpers/` (9 files)
- `types.py` — 14 entity TypedDicts (all `common_fields: true` here, so all carry `id`/`created_at`/`updated_at`/`version`) + 20 status/role enums
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per each of the 59 PRD endpoints (including `PATCH /school/sections/{id}` and `POST /school/_clock/set_current_utc`)
- `api_errors.py` — all 30 error IDs with the §5 HTTP status map, registered via `set_error_http_status_map` at import time
- `assertions.py` — per-entity assertions plus `assert_invoice_money_invariants` (balance = total_due − credit − paid + late_fees)
- `factories.py`, `constants.py` (standard year config + startup clock + canonical session dates), `test_users.py` (opaque-role shared constants + mandatory `make_teacher_headers`/`make_parent_headers` entity-backed builders), `fixtures.py` (tiered composites: `setup_open_year`, `setup_open_year_with_section`, `setup_family_with_enrollment`, `setup_family_with_invoice`, `setup_section_with_attendance`, assistance-pipeline helpers, OCC-aware `enroll_student_fresh`/`enroll_students_sequential`, `issue_invoice_fresh`), and the barrel `__init__.py`

## Stage 2 — `test_suite/` (conftest + 9 files, 82 test functions)
Organized by concern: `test_01` year/security-plan/closures, `test_02` teachers/sections/placement, `test_03` enrollment capacity + OCC, `test_04` tuition calculation, `test_05` sessions/attendance/milestones, `test_06` assistance pipeline, `test_07` invoices/payments/late fees/withdrawals, `test_08` cascades + volunteering, `test_09` validation priority/envelope/auth/pagination.

## Audit results (all green)
- **Coverage:** all 19 queue-A difficulty instances have ≥2 tests; all 46 non-stub queue-B corner instances have ≥1 test (65/65 covered). The 4 `excluded_because` stubs were not translated; their difficulty-instance cross-references all resolve.
- **Tag discipline:** every test docstring ends with exactly one `Design: Difficulty/...` or `Design: Corner/...` line copied verbatim from the source yaml `name:`; zero unknown tags, zero dual/untagged tests.
- **PRD citations:** every docstring quote survives a normalized verbatim grep of `PRD.md` (2 ellipsis-abbreviated citations were rewritten to full-sentence quotes during the sweep). Every asserted `error_id` appears in PRD prose sections §1–§4, not just the §5 table.
- **No leaks:** no `pytest.mark.skip`/`skipif`/`xfail` anywhere; no scaffold references in comments/docstrings; every `from test_helpers import ...` name resolves.
- **Two-reader adjudication:** the priority-pair tests rest on PRD §2.8's explicit "fixed priority order... earlier failures mask later ones deterministically" sentence, so they pass the unique-derivability filter; no instance needed to be dropped for coverage or derivability failure.

All files compile (`py_compile` clean).

## Step 6: Generate Implementation — 2026-08-15T01:10:00.000Z

The implementation is complete. Summary of what was built:

**Implementation at `/home/ubuntu/github/CodingPRD/tasks/task_1900_religious_school_weekend_education/workspace/implementation/`**

- `start.sh` — foreground launcher with guarded `pip install` (skips install once flask is present), `exec python3 app.py`, reads `PORT` (default 10000), binds `0.0.0.0`.
- `requirements.txt` — `flask>=2.0,<4.0`.
- `app.py` — Flask app with blueprint registration and `ApiError`/404/400/500 handlers producing the scaffold envelope.
- `db.py` — In-memory store (empty at boot, no seeding), `Clock` (logical clock default `2026-08-01T00:00:00Z`), ISO parse/format helpers with 3-fractional-digit UTC timestamps, monotonic `_seq` for created_at tie-breaking per the sibling-rank rule.
- `errors.py` — all 27 catalog error IDs with their HTTP statuses.
- `response.py` — `{meta, response_type, data}` envelope; pagination meta fields `limit/offset/total_count/has_more`; `limit` default 10/min 1/max 100, `offset` default 0.
- `middleware.py` — `X-User-Role`/`X-User-ID` auth, role allowlist enforcement.
- `services/core.py` — record factory, derived `staffing_status`, `enrollment_net_tuition` (round-half-up per line, sibling-rank by `created_at`+`_seq`, strict `<` early-bird), `attendance_percentage` (PRESENT=1.0, EXCUSED=0.5, ABSENT=0, no-entry=0; HELD-with-attendance only; projected adds SCHEDULED to both numerator and denominator), milestone re-evaluation, commitment totals/regression, family outstanding recompute.
- `routes/` — one file per resource group: `school_years.py` (years, security plans, closures, accrual, clock), `families.py`, `teachers.py` (with the 3-hop separation cascade), `sections.py` (room/day/time half-open overlap, capacity-below-enrolled), `enrollments.py` (OCC on `Section.version`, auto-create Milestone+VolunteerCommitment, withdrawal with refund tiers and credit grant), `invoices.py` (issue/supersede, award calc PERCENT_OF_NET vs FLAT_CAP, credit consumption, payment waterfall with remainder to credit, void reversal), `assistance.py` (segregation of duties, award params), `sessions.py` (closure/out-of-year/future gates, staffed requirement, attendance upsert, REGISTERED→ACTIVE on hold), `milestones.py` (two-gate schedule ordering), `volunteer.py` (entries, void regress, waive with buyout-fee void).

Verified end-to-end against the booted server:
- Year/plan open gating (`ERR_SECURITY_PLAN_NOT_ACTIVE`)
- Sibling + early-bird tuition math (`92500`, `83250`) with correct per-line rounding
- OCC `ERR_STALE_VERSION` on section version mismatch
- Invoice issue, waterfall payment, void reversal (PAID→PARTIALLY_PAID→ISSUED)
- Withdrawal refund tiers with credit granted only when paid
- Session create/hold/cancel, future-date and out-of-year rejections, attendance upsert, REGISTERED→ACTIVE
- Milestone TRACKING↔ELIGIBLE, two-gate schedule (ELIGIBLE then FULFILLED), SCHEDULED→ELIGIBLE revert on entry void
- Late-fee accrual with pre-fee snapshot and no same-run compounding
- Year close sweep (sessions→CANCELLED YEAR_CLOSE, OPEN shortfall→DEFAULTED + fee-only invoice, sections→CLOSED, enrollments→COMPLETED)
- Assistance pipeline: duplicate application rejection, `reviewed_by_user_id` capture, `ERR_SEGREGATION_OF_DUTIES`, `ERR_AWARD_PARAMS_INVALID`, FLAT_CAP applied to invoice
- Teacher separation cascade: unstaff → cancel SCHEDULED sessions with `TEACHER_SEPARATION` → milestone re-eval
- Auth: missing headers→401, wrong role→403, parent cross-family→403 `ERR_OWNERSHIP_MISMATCH`
- Cold boot via `bash start.sh` from a fresh process resets the clock and store (per-test-server isolation contract satisfied).

## Step 7: Run Tests and Iterate — 2026-08-15T01:25:00.000Z

## Summary — task_1900 Step 7 complete, all green

**Iterations run:** 2 sweeps (16 server-isolated rounds total).

**Result:** All 8 rounds of the final parallel sweep pass **89/89** — exit criterion met.

### Tests deleted (1)

- `test_enrollment_extra_field_rejected` (`test_suite/test_02_teachers_sections_placement.py`, class `TestPlacement`) — **unique-derivability failure on a scaffold-only rule**. The test asserted that an enrollment payload containing an extra `estimated_tuition_cents` key must be rejected with `ERR_INVALID_REQUEST`. This traces to `SCAFFOLD_CORNER_DESIGN.yaml` corner `enrollment_extra_field_rejected` ("computed values are server-owned"), but no PRD sentence requires rejecting unknown payload fields: §2.8 step 5 covers only required-field presence, types, enum membership, and ranges; §3.3 says the payload "carries the `student_id` and the `expected_section_version`" without forbidding additional keys. Two-reader experiment: a PRD-faithful implementer who ignores unknown JSON fields (standard REST behavior) fails this test while violating no PRD prose. Deleted per the PRD-First contract. (Feedback for unit-test-generator: system-fields claim-type corners asserting unknown-field rejection are not uniquely derivable from payload-shape prose.)

### Fixes applied to `test_helpers/`
None — fixtures, factories, and role-header builders were all PRD-consistent.

### Fixes applied to `implementation/`
None — the implementation was correct; the only failure in iteration 1 (identical across all 8 rounds, no flakiness) was the unfair test above. No implementation check was weakened or removed.

## Step 8: Finalize PRD — 2026-08-15T01:32:00.000Z

Done. PRD_FINALIZED.md is written at `/home/ubuntu/github/CodingPRD/tasks/task_1900_religious_school_weekend_education/workspace/PRD_FINALIZED.md` with exactly one scoped edit.

**Line counts / delta:** PRD.md 312 lines, PRD_FINALIZED.md 312 lines — 0% delta (one line revised in place, no lines added or removed).

**Changes:**
- §2.8 step 5 (Request shape) — revise — appended a sentence pinning that request-shape validation is limited to the fields each endpoint specifies, that additional/unrecognized payload fields are ignored rather than rejected with `ERR_INVALID_REQUEST`, and that this includes client-supplied copies of computed/server-managed values such as `estimated_tuition_cents` on the enrollment payload — `implementation/routes/enrollments.py:27-35, 68-86`.

**Pre-edit search log (NO-NEW-MISMATCH RULE):**

Edit 1 (the only edit):
- (a) Subject: server treatment of request-payload fields beyond those specified per endpoint — unknown/extra keys, including client-supplied computed/server-managed values.
- (b) Impl paths enumerated and read/grepped: every write endpoint reads only its named fields and never inspects the key set — `routes/enrollments.py:27-35` (create enrollment; record built from `base_record()` plus computed values at lines 68-86, so a client-sent `estimated_tuition_cents` is never read), `routes/assistance.py:24-27` and `:137-143` (apply, decide), `routes/invoices.py:27-33` and `:177-179` (issue, payment), `routes/families.py:17-20` and `:55-58` (family, student), `routes/milestones.py:68-69` (schedule), `routes/volunteer.py:59-61` (log entry), `routes/sessions.py:26-27` (session create) and `:146-186` (attendance — nested entry objects also read only `student_id`/`status`, rebuilding each stored entry fresh at line 183), `routes/teachers.py:23-26`, `routes/sections.py:24-33` and `:120-122` (patch uses an `__UNSET__` sentinel for its two named fields only), `routes/school_years.py:59-122, 294-295, 383-386, 451-452`. Global modules `middleware.py`, `response.py`, `app.py` contain no payload validation. Greps for `set(body`, `body.keys()`, `del body`, `body.pop` across all of `implementation/` returned zero hits, and no route does a wholesale `rec.update(body)`.
- (c) Wording adjustment: phrased as a permissive universal ("not rejected … simply ignored") rather than a restrictive one ("payloads contain only …"), because all 18 enumerated endpoints uniformly ignore extras and none reject them; the `estimated_tuition_cents` example was explicitly verified against enrollments.py before being named, since the deleted test used exactly that field.

No other step_7_diff items existed (no implementation fixes, no test_helper fixes), so no other edits were made.

## Step 9: Complete PRD — 2026-08-15T01:50:00.000Z

Done. `/home/ubuntu/github/CodingPRD/tasks/task_1900_religious_school_weekend_education/workspace/PRD_COMPLETED.md` produced as a minimal patch over `PRD_FINALIZED.md`.

**Size**: PRD_FINALIZED.md 312 lines / 54,240 bytes → PRD_COMPLETED.md 312 lines / 58,671 bytes (char-delta +4,396 chars; all edits in-paragraph, no new sections, line count unchanged).

**Counts**: 15 ambiguity-pins, 6 mismatch-revisions (one edit is a revise+insert pair counted once each below; 21 bullet items total across 20 edited paragraphs).

- §2.1 — insert — ambiguity — Parent passing a `family_id` filter ≠ own id on family-scoped listings is rejected `ERR_OWNERSHIP_MISMATCH` — routes/enrollments.py:156, invoices.py:150, milestones.py:39, volunteer.py:38
- §2.3 — insert — ambiguity — non-integer/out-of-range `limit` (1–100) or negative `offset` → `ERR_INVALID_REQUEST`; `created_at` ties break by server request-arrival order; `has_more` = offset + returned < total_count — response.py:64-88, response.py:37, routes/sections.py:110 (and all list endpoints)
- §2.4 — revise — mismatch — milestone re-evaluations and commitment recompute-on-entry-void refresh `updated_at` only, never bump `version` (PRD said "increments with every modification") — services/core.py:345, 385-386, routes/volunteer.py:96
- §2.4 — revise — mismatch — family-`version` bump list extended with the buyout-fee-invoice void on waiving a DEFAULTED commitment — routes/volunteer.py:122-125
- §2.5 — insert — ambiguity — envelope `api_request_timestamp` is minted from the logical clock — response.py:17
- §2.5 — revise — ambiguity — clock set is unconditional (forward or backward), not only "advances" — db.py:22-25, routes/school_years.py:458
- §2.8 step 3 — insert — ambiguity — ownership-by-loaded-resource (enrollment/invoice/milestone/application/commitment/session id in path; `student_id` in enrollment payload): resource load (ERR_NOT_FOUND) and, for enrollment creation, shape checks precede the ownership comparison — routes/enrollments.py:26-41, routes/sessions.py:140-144
- §2.8 step 5 — insert — ambiguity — empty strings rejected as missing for name/label fields (`family_name`, `primary_email`, student/teacher `full_name`, teacher `email`, application `reason`, section `room`) — routes/families.py:21-24,60; teachers.py:28-30; assistance.py:31; sections.py:41
- §2.8 step 5 — insert — ambiguity — body-carried ids existence-checked where first used: `student_id`/`school_year_id` immediately after shape; `teacher_id` bundled with the HIRED check — routes/enrollments.py:37, invoices.py:37-39, assistance.py:36-38, sections.py:53-55,135-137
- §2.8 step 9 — revise — ambiguity — session date outside the year is detected before the inside-a-closure check — routes/sessions.py:42-52
- §3.1 — insert — ambiguity — `sibling_discount_pcts` must be non-empty; elements validated only as numbers (no per-element range) — routes/school_years.py:86-91
- §3.2 — insert — ambiguity — PATCH may set `teacher_id` to null (section becomes UNSTAFFED); capacity changes re-apply the automatic OPEN↔FULL occupancy flip — routes/sections.py:140,147-150
- §3.4 — revise — mismatch — dropped the "held while the student's enrollment was REGISTERED/ACTIVE" eligibility restriction; impl counts every HELD session with non-empty attendance in the section (pre-enrollment sessions weight 0.0) — services/core.py:274-297
- §3.4 — revise — mismatch — "cancellation of any kind" narrowed to exclude the year-close sweep — routes/school_years.py:184-190
- §3.4 — insert — ambiguity — withdraw-then-re-enroll keeps the single original milestone; percentages computed against the earliest-created enrollment's section — services/core.py:325-336,252-258
- §3.5 — insert — ambiguity — each start-review re-records `reviewed_by_user_id`; a different officer on a later round becomes the segregated party — routes/assistance.py:116-117
- §3.5 — revise — mismatch — out-of-enum `award_method` on APPROVED is `ERR_INVALID_REQUEST` (shape), not `ERR_AWARD_PARAMS_INVALID`; award fields on a DENIED decide are ignored — routes/assistance.py:146-149,182-185
- §3.6 — insert — ambiguity — payment waterfall ties beyond `created_at` break by request-arrival order — routes/invoices.py:190
- §3.6 — insert — ambiguity — `accrued_invoice_ids` listed in invoice creation order — routes/school_years.py:256-272
- §3.7 — insert — ambiguity — only a positive computed credit is granted; a zero credit leaves family balances/version and `credit_applied` untouched — routes/enrollments.py:233-239
- §3.8 — insert — ambiguity — entries may be logged on a commitment in any status; auto-fulfill flip applies only from OPEN (DEFAULTED/WAIVED never reopen) — routes/volunteer.py:53-79
- §3.8 — revise — mismatch — waiving DEFAULTED voids the buyout-fee invoice only when still open (ISSUED/PARTIALLY_PAID); a PAID fee invoice stands — routes/volunteer.py:113-126

Key findings worth flagging: the two genuine behavioral mismatches were (1) impl's attendance math ignores the PRD's "held while enrolled" timing clause, and (2) impl's milestone/commitment recomputation paths deliberately skip version bumps despite the PRD's universal version rule — both resolved in impl's favor per the mandate.
