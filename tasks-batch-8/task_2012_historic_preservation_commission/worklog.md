# Worklog — task_2012_historic_preservation_commission

## Step 1: Create Task Directory — 2026-08-15T06:32:00.000Z

Pre-existing per pipeline invocation: `tasks/task_2012_historic_preservation_commission/` and `workspace/` verified present and empty. No index scan performed (per instructions).

## Step 2: Generate Scaffold — 2026-08-15T07:03:00.000Z

## Report

Generated the full scaffold package for task 2012 at `/home/ubuntu/github/CodingPRD/tasks/task_2012_historic_preservation_commission/`:

- `SCAFFOLD.yaml` — §1.0–§1.7 only (no difficulty/corner keys): fixed response envelope, 13 entities, 10 state machines, 1 OCC concurrency rule, 7 calculation rules, 10-priority validation table, 62 endpoints, 36 error codes, 5 roles.
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top-level `scaffold_difficulty_design:` key; 18 instances (2 per each of the 9 rules), all with structured, replayed `setup_api_calls`/`trigger` chains and pre-computed literal asserts.
- `SCAFFOLD_CORNER_DESIGN.yaml` — single top-level `scaffold_corner_design:` key; 53 active instances + 2 `excluded_because:` stubs across all 9 claim-guide sections.

**Design profile** (Expert tier): compliance/audit + workflow-orchestration archetypes; flat FK topology; cyclic state shape; segregation-of-duties role model; logical-clock endpoint `POST /preservation/_clock/set_current_utc` with mandatory default `2026-08-01T00:00:00Z`.

**Key mechanics designed for depth:**
- Dual-variant calcs on two domains: application fee (provisional declared vs final verified + hearing surcharge) and violation penalty (demand projection vs final marginal-tier accrual with 10%-of-assessed-value cap).
- Combinatorial formulas in distinct modes: 5-input review-track branch formula (mode a), pinned per-item-round-then-sum fee rounding (mode b), and the demolition-delay/hardship filing-window circular dependency with pinned evaluation order (mode c).
- Cyclic machines: application resubmission loop and hearing continue/reschedule loop; branching violation machine.
- Cascades: appeal-sustain chain of depth 3 (Appeal→Application→Violation→Property) and demolition-completion chain of depth 2 (Certificate→Property→District census/posture).
- Priority conflicts: state-vs-temporal (decided hearing reschedule) and referential-vs-fiscal (certificate with open violation + unpaid fee).
- Boundaries: >= $10,000 review threshold, inclusive day-30 appeal window, day-60/61 court-escalation, day-31 penalty tier, exact 15-day notice, half-open delay expiry at the end instant.
- One true-race OCC rule (reclassify-stale-property, 412); a hearing-create OCC rule was drafted then deliberately removed because the mandatory serial-observability filter reclassifies it as a state precondition.

**Verification:** `scaffold_lint.py` verdict block (verbatim): `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (62 endpoints, 13 entities, 18 + 53 instances, 561 calls scanned.) Additional self-checks confirmed: instance names unique across both design files (73 total), every error code referenced by §1.2/§1.4/§1.2.1, excluded-stub citations resolve, and no forbidden concurrency vocabulary anywhere.

## Step 3: Copy Shared Files — 2026-08-15T07:05:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_2012_historic_preservation_commission/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-15T07:20:00.000Z

## Report

**Generated**: `/home/ubuntu/github/CodingPRD/tasks/task_2012_historic_preservation_commission/workspace/PRD.md` (340 lines) from `SCAFFOLD.yaml`, per the prd-bench-doc-generator skill. The two forbidden difficulty/corner design files were not opened or referenced.

**Structure** (domain-derived, not template-copied):
- §1: 2-paragraph introduction from the commission's audit/consistency/enforcement angle
- §2: 10 subsections — RBAC (all 5 roles with identity prose), §2.2 verbatim response envelope (byte-identical to `section-2.2-response-structure.md`), pagination, common resource properties (incl. PublicComment's id/created_at-only exception), the logical clock (startup default `2026-08-01T00:00:00Z`, no wall-clock fallback), integer-cent money with pinned rounding, OCC, the 10-layer gatekeeping pipeline with masking semantics, district census/posture, atomic cascades
- §3: 9 subsections in chronological lifecycle order (inventory → intake → completeness review → hearings/decision → fees/withdrawal → appeals → demolition delay/hardship → violations/after-the-fact → certificates), with endpoint parameters deliberately scattered (e.g., `after_the_fact`/`violation_id` live in §3.8, not §3.2; `guideline_override_ack` mechanics split across §3.1/§3.3/§3.4)
- §4: 62-row endpoint table, 4 columns; §5: 35-row error table, 2 columns; document ends at §5 with no audit footer

**Hard Contract Reports**:

```
Field coverage check:
- entities[].fields + endpoint inputs + query params + array sub-fields: 98 required, 98 present, 0 missing
Status: PASS
```

```
Rule coverage check:
- validations[] priority: 10 layers checked, 10 expressed in order with masking prose
- concurrency_rules[]: 1 checked, 1 expressed (write endpoint + expected_property_version + ERR_STALE_PROPERTY_VERSION 412, pre-state check, no race framing)
- state transitions: 33 transition groups checked, 33 fully expressed (from/to states, preconditions paired with error IDs, side effects)
- calculations[]: 7 checked, 7 fully expressed (pinned per-item fee rounding with all 13 constants; 3-branch review track with inclusive 1,000,000-cent boundary and no-district rule; marginal civil-penalty tiers with strict penalty_capped and both variant stop dates; delay schedule; refund schedule; census; inclusive notice window)
- validations[] conditions: 35 error IDs all present in §2/§3 prose, matchable to conditions
- endpoints[] side effects / applies_to scopes: all expressed (pipeline layers enumerate guarded endpoint sets)
- entities[].fields structured content: all defaults/initials/nullability/recompute moments placed in prose
- sibling-branch symmetry: decide outcomes on both tracks, 6 withdraw from-states, appeal/hardship outcomes, verify-compliance and close paths — equal density
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 471
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Auxiliary checks: §4 table contains all 62 scaffold endpoints with matching method+path rows; §5 contains all 35 errors with scaffold-exact HTTP statuses; no pseudocode operators or approximating wording in calculation prose (rates rendered as exact percentages, all thresholds with inclusive/exclusive boundaries stated, e.g., "exactly fifteen days before passes, one second later fails").

## Step 5: Generate Unit Tests — 2026-08-15T07:50:00.000Z

## What was generated

**`test_helpers/`** (Stage 1, 9 files) at `/home/ubuntu/github/CodingPRD/tasks/task_2012_historic_preservation_commission/test_helpers/`:
- `types.py` — 13 entity TypedDicts + all status/role enums; `PublicComment` correctly carries only `id`/`created_at` (no `updated_at`/`version`)
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD §4 endpoint (44 endpoints incl. the logical clock)
- `api_errors.py` — all 35 error IDs with the §5 HTTP status map, registered via `set_error_http_status_map`
- `assertions.py` — per-entity `assert_*()`, `assert_district_census()`, and format-agnostic `assert_instant_equal()` (logical-clock stamps are compared as instants, since PRD does not pin the echo format)
- `factories.py`, `constants.py` (fee schedule, penalty tiers, delay windows, clock anchors)
- `test_users.py` — opaque roles as shared constants; entity-backed `Applicant` gets mandatory `make_applicant_headers(owner["id"])`
- `fixtures.py` — composite builders: `setup_staff_track_accepted`, `setup_commission_track_accepted`, `setup_hearing_scheduled/open`, `setup_staff_approved/denied`, `setup_after_the_fact_pending`, `setup_approved_demolition` (fetches the created delay), `setup_certificate_issued`

**`test_suite/`** (Stage 2) — `conftest.py` + 11 files (`test_01_districts_inventory` … `test_11_certificates`), **88 tests collected**.

## Coverage audit (verified programmatically)
- Queue A: 18/18 difficulty instances × exactly 2 tests each
- Queue B: 52/53 non-stub corner instances × 1 test each; both `excluded_because:` stubs untranslated (cross-references resolve); every test's docstring ends with exactly one resolving `Design:` tag
- Every quoted PRD citation verified verbatim against `PRD.md` (whitespace-normalized); every asserted `error_id` is named in quoted PRD prose; no `skip`/`skipif`/`xfail`; pyflakes clean; no "scaffold" references

## Three adjudications you should know about

1. **SKIPPED `Corner/entities/application_computed_fee_input_ignored`** — the instance asserts a client-supplied `provisional_fee_cents` is ignored. PRD §2.6 ("never edited directly") does not uniquely derive *ignore-and-compute* vs *reject as malformed* (§2.8's `ERR_VALIDATION` covers "malformed bodies"), so two PRD-only readers diverge. Gap left as a gap.
2. **`Corner/endpoints/hearing_create_on_staff_track_rejected`** — the index asserts `ERR_COMMISSION_HEARING_REQUIRED`, but PRD §3.4 explicitly states: scheduling a hearing for "a `STAFF`-track `ACCEPTED` application — is rejected with `ERR_INVALID_STATE`." The test asserts the PRD-stated error.
3. **`Corner/calculations/hardship_grant_replaces_delay_end`** — the index's `setup_api_calls` never advances the clock before filing the hardship, which would violate the PRD window ("`filed_at` must be strictly after the application's `decided_at`"). The test files at 2026-09-01, matching the instance's own annotation ("hardship filed 2026-09-01") and the PRD window.

Also relaxed one sub-assertion: `district_creation_defaults` omits `version == 1` (PRD §2.4 never pins the initial version value; §2.9 posture/counter defaults are asserted exactly).

## Step 6: Generate Implementation — 2026-08-15T07:50:00.000Z

## What was built

`/home/ubuntu/github/CodingPRD/tasks/task_2012_historic_preservation_commission/workspace/implementation/`:

- **start.sh** — guarded install (`if ! python3 -c "import flask"` then pip install) + `exec python3 app.py`; binds `0.0.0.0:$PORT` (default 10000), boots in ~1s on reinstall-free reboots.
- **app.py** — Flask entry, error handlers (ApiError → envelope; 404/405 → `ERR_NOT_FOUND`; unexpected → traceback + `ERR_VALIDATION`).
- **db.py** — empty in-memory store (13 collections) + creation sequence counter; **no seeding at boot**.
- **errors.py** — all 35 error IDs with exact HTTP statuses from scaffold §1.6.
- **response.py** — envelope `{meta:{api_request_id, api_request_timestamp}, response_type, data}`, list meta adds `limit/offset/total_count/has_more` (defaults 10/0, bounds 1–100).
- **middleware.py** — `X-User-ID`/`X-User-Role` auth; 5 roles; `ERR_UNAUTHENTICATED` 401 / `ERR_FORBIDDEN_ROLE` 403.
- **util.py** — logical clock (default exactly `2026-08-01T00:00:00Z`, never wall-clock; timestamps round-trip at set precision), wall-clock `created_at`/`updated_at` with 3 fractional digits, Decimal half-up money helpers.
- **validate.py** — request-shape gate (`ERR_VALIDATION` 400): typed fields, enums, datetime parsing, work-item/verified-item/section array shapes.
- **services/calculations.py** — pinned constants and formulas: per-item fee (`base + round_half_up(rate·cost)` per item, then sum; +20000 surcharge after sum when COMMISSION), review-track 3-branch rule (type → cost ≥ 1,000,000 → CONTRIBUTING+visible+LANDMARK/ICONIC), marginal civil-penalty tiers (10k/20k/50k per day over 30/30/∞ day bands) with 10%-of-assessed cap, demolition-delay schedule (base 90/180/365 + 30 per postponement, max 2; hardship lift +10 days; lazy `EXPIRED` at effective end), stage refund schedule (100/50/0%), inclusive 15-day notice window.
- **services/core.py + workflows.py** — record lifecycle (`version` bumps on every mutation incl. cascades), district census/posture recounts (always equal to full recount), property enforcement counters, live meeting occupancy, and the atomic cascades: decision (hearing mirror, demolition delay + property advance, after-the-fact violation resolution), withdrawal (refund + hearing release), appeal-sustain (application→violation→property chain), demolition completion (property→district census).
- **routes/** — all 46 endpoints under `/preservation`, each enforcing the PRD §2.8 pipeline order: shape+auth → role/ownership → existence (path left-to-right, then body refs) → OCC (`expected_property_version` → 412) → state → safety → referential → temporal → structural → fiscal.

## Key findings during the build

- **PRD vs. corner-design conflict resolved for PRD**: hearing creation on a STAFF-track `ACCEPTED` application returns `ERR_INVALID_STATE` (PRD §3.4 literal), not the corner design's `ERR_COMMISSION_HEARING_REQUIRED`. The generated test suite cites the PRD prose and expects `ERR_INVALID_STATE`; that was the only failing test (87/88 → 88/88).
- Verified exact design-file numbers end-to-end: provisional 27600 vs final 49300, per-item rounding 30266 (not 30267), penalty day-31 = 320000 and day-45 = 600000, cap binds at 10% of assessed, delay end 2026-10-30/2026-12-29, hardship final end 2026-09-20, certificate deadline +365d, appeal finalize boundary at exactly decided_at+30d, escalation day-60 rejected / day-61 allowed, OCC 412 on stale reclassify, and the referential-beats-fiscal certificate gate.

Results artifacts are at `workspace/results.{1..4}.json` (rounds 2–4: 88 passed, 0 failed).

## Step 7: Run Tests and Iterate — 2026-08-15T08:05:00.000Z

**Summary**

- **Iterations run**: 1 fresh 8-round parallel stability sweep (rounds 1–8 all clean: 88 passed / 88 total, 0 failed, 0 errors, ~118s per round). This is consistent with the pre-existing artifacts at `workspace/results.{2,3,4}.json` (all 88/88); the only historical failure — `test_hearing_create_on_staff_track_rejected` in the old `workspace/results.1.json` — was the known PRD-vs-corner-design adjudication (PRD §3.4 mandates `ERR_INVALID_STATE` for scheduling a hearing on a STAFF-track ACCEPTED application), already resolved in favor of the PRD during Step 6 implementation generation, before this diagnostic loop began.
- **Tests deleted**: none. Every assertion in the 88-test suite traces to verbatim PRD prose (citation-verified at generation time per the worklog audit) and no failures surfaced to trigger the STEP 1 coverage / unique-derivability checks.
- **Fixes applied to `test_helpers/`**: none this loop.
- **Fixes applied to `implementation/`**: none this loop.

Key paths:
- Results: `/home/ubuntu/github/CodingPRD/tasks/task_2012_historic_preservation_commission/workspace/implementation/results.{1..8}.json`
- PRD: `/home/ubuntu/github/CodingPRD/tasks/task_2012_historic_preservation_commission/workspace/PRD.md`
- Implementation: `/home/ubuntu/github/CodingPRD/tasks/task_2012_historic_preservation_commission/workspace/implementation/`
- Tests: `/home/ubuntu/github/CodingPRD/tasks/task_2012_historic_preservation_commission/test_suite/` + `test_helpers/`

The task is stable: 8/8 concurrent per-test-server-isolation rounds green, no flakiness signals, no further action required.

## Step 8: Finalize PRD — SKIPPED — 2026-08-15T08:05:30.000Z

Skipped per the skip condition: Step 7 exited on its first 8-round sweep with 0 deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes — zero iterations beyond the baseline, so `PRD.md` already determines every behavior the implementation exhibits. No `PRD_FINALIZED.md` produced.

## Step 9: Complete PRD — 2026-08-15T08:20:00.000Z

PRD_COMPLETED.md is complete. All edits are inline — no new sections or paragraphs, and no behavior invented beyond what `implementation/` exhibits.

## Summary

**Source:** `workspace/PRD.md` (no `PRD_FINALIZED.md` present) → `workspace/PRD_COMPLETED.md`
**Line counts:** 339 → 339 (all changes inline). **Char delta:** 56,627 → 60,933 (+4,306).
**Counts:** 20 ambiguity-pins, 1 mismatch-revision (21 changed prose locations).

Changes:

- §2.3 — insert — ambiguity — invalid pagination params (non-integer/out-of-range `limit`, negative/non-integer `offset`) rejected with `ERR_VALIDATION` — implementation/routes/helpers.py:17-39
- §2.3 — revise — ambiguity — list sort ties on creation timestamp broken by creation order — implementation/routes/helpers.py:53, implementation/db.py:30-32
- §2.4 — revise — ambiguity — `version` starts at 1 at creation — implementation/services/core.py:11-21
- §2.5 — insert — ambiguity — logical clock governs business timestamps; `created_at`/`updated_at`/`api_request_timestamp` are wall-clock; logical-clock timestamps render at the precision the clock was set with (seconds → no fraction, ms → 3 digits, finer → 6) — implementation/util.py:29-62, services/core.py:14,24-26
- §2.8 layer 1 — insert — ambiguity — within layer 1, header authentication is evaluated before body-shape validation — implementation/middleware.py:30-42, e.g. routes/districts.py:28-33
- §2.8 layer 2 — insert — ambiguity — applicant ownership is compared against the payload `owner_id` before existence at intake, and against the loaded resource's `owner_id` immediately after the reference resolves elsewhere — implementation/routes/applications.py:77-82,222-225, appeals.py:30-33,111-114, hardship_reviews.py:37-40
- §3.1 — insert — ambiguity — district PATCH bumps `version` once when ≥1 updatable field supplied (even same-value); a fieldless PATCH changes nothing — implementation/routes/districts.py:74-87
- §3.1 — revise — ambiguity — duplicate `parcel_number` → `ERR_VALIDATION`; `construction_year` integer, `assessed_value_cents` non-negative integer else `ERR_VALIDATION` — implementation/routes/properties.py:31-41
- §3.1 — revise — ambiguity — district-scoped property collection includes all assigned properties, `DEMOLISHED` included — implementation/routes/districts.py:90-95
- §3.2 — revise — ambiguity — `estimated_cost_cents` is a non-negative integer else `ERR_VALIDATION` — implementation/validate.py:149-151
- §3.2 — insert — ambiguity — `violation_id` required when `after_the_fact` true, absent/null when false (`ERR_VALIDATION`); district-review rejection surfaces before after-the-fact linkage gates — implementation/routes/applications.py:69-75,96-106
- §3.3 — revise — ambiguity — `verified_cost_cents` non-negative integer (`ERR_VALIDATION`); `verified_work_items` may be empty (verified total zero) — implementation/validate.py:160-176
- §3.4 — revise — ambiguity — `agenda_capacity` is a non-negative integer else `ERR_VALIDATION` — implementation/routes/meetings.py:20
- §3.4 — insert — ambiguity — a `Commissioner` deciding a `STAFF`-track `ACCEPTED` application is rejected with `ERR_FORBIDDEN_ROLE` — implementation/routes/applications.py:299-302
- §3.4 — insert — ambiguity — decision structural-check order pinned: track authority/segregation → documentary requirements → superseded-guideline ack → demolition-delay overlap last before commit — implementation/routes/applications.py:294-340
- §3.4 — insert — ambiguity — superseded-guideline check never fires when `guideline_set_id` is null — implementation/routes/applications.py:324
- §3.4 — insert — ambiguity — application-list filter semantics: `district_id` via subject property's district; `work_category` matches ≥1 work item of that category — implementation/routes/applications.py:160-175
- §3.5 — insert — ambiguity — `amount_cents` must be a positive integer (`ERR_VALIDATION`); payments accepted in every status except `WITHDRAWN`/`DENIED_FINAL` (`ERR_INVALID_STATE`) — implementation/routes/applications.py:417,422-424
- §3.5 — revise — **mismatch** — "at any point before it reaches a decision terminal state" replaced with the exact seven withdrawable states (`SUBMITTED`, `UNDER_STAFF_REVIEW`, `INCOMPLETE`, `ACCEPTED`, `HEARING_SCHEDULED`, `HEARING_DEFERRED`, `HEARING_OPEN`); all others incl. `DENIED` → `ERR_INVALID_STATE` — implementation/routes/applications.py:40-43,382-384
- §3.7 — revise — ambiguity — base delay for a property outside any district is the `LOCAL` base (90 days) — implementation/services/workflows.py:22, calculations.py:47
- §3.7 — revise — ambiguity — `claimed_rate_of_return_pct` any JSON number; `appraisal_basis_cents` non-negative integer — implementation/routes/hardship_reviews.py:34-35
- §3.8 — insert — ambiguity — closure adjusts no property counters; a case closed from `COURT_REFERRAL` still counts against the open-violation tally at certificate issuance — implementation/routes/violations.py:137-155 (no `recompute_property_enforcement` call), services/core.py:64-79, routes/certificates.py:42
- §3.9 — insert — ambiguity — certificate gate order pinned: open-violation check → one-certificate check → fee-balance check — implementation/routes/certificates.py:40-53
- §4 — revise — ambiguity — demolition-delay list filters named: `property_id`, `application_id`, `status` — implementation/routes/demolition_delays.py:23-28

Everything else in the implementation (all endpoint paths/methods/roles, state machines, fee/penalty/refund/delay formulas and constants, temporal window boundaries and their inclusivity, cascades, OCC, response envelope, error catalog) was already uniquely pinned by the PRD and left untouched.
