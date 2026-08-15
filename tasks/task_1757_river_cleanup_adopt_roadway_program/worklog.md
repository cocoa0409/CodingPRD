# Worklog — task_1757_river_cleanup_adopt_roadway_program

## Step 1: Create Task Directory — 2026-08-14T13:54:00.000Z

Pre-assigned directory `tasks/task_1757_river_cleanup_adopt_roadway_program/` with `workspace/` subdirectory verified to exist. No index scan performed per instructions.

## Step 2: Generate Scaffold — 2026-08-14T15:14:00.000Z

Done. The three scaffold artifacts for task 1757 are generated and lint-clean.

**Files written:**
- `/home/ubuntu/github/CodingPRD/tasks/task_1757_river_cleanup_adopt_roadway_program/SCAFFOLD.yaml` — §1.0–§1.7 (no difficulty/corner keys)
- `/home/ubuntu/github/CodingPRD/tasks/task_1757_river_cleanup_adopt_roadway_program/SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top-level `scaffold_difficulty_design` (§1.8)
- `/home/ubuntu/github/CodingPRD/tasks/task_1757_river_cleanup_adopt_roadway_program/SCAFFOLD_CORNER_DESIGN.yaml` — single top-level `scaffold_corner_design` (§1.9)

**Design summary:**
- **Complexity profile**: compliance_audit primary + temporal_windowing secondary; layers = rate/threshold triggers, derived-field reconciliation, OCC, cascading side effects; flat FK topology; cyclic state machines; approval_chain roles (GroupLeader `entity_backed:AdopterGroup`, ProgramCoordinator `opaque`).
- **Surface**: 10 entities (AdopterGroup, RoadSegment, AdoptionAgreement, CleanupEvent, VolunteerWaiver with self-referential supervisor FK, SupplyDepot, SupplyDistribution, immutable DebrisReport, HazardReport, SignRecognition), 43 endpoints including `POST /_clock/set_current_utc` (default 2026-08-01T00:00:00Z, drives NO_SHOW / waiver-expiry / auto-suspend / auto-expiry sweeps), 42 domain error codes, 8 calculations.
- **§1.8**: 18 instances, exactly 2 per rule — highlights: ROLLING-vs-ANNIVERSARY compliance windows diverging on identical completion history; MEASURED-vs-ESTIMATED debris weight (40.0 vs 38.4); water-surcharge supply allocation (35 vs 28 bags); per-line-then-sum rounding pin (20.1 not 20.0); suspend→cancel→reconcile→restock depth-3 cascade vs report→complete→recount→reinstate cascade; state-beats-safety and temporal-beats-constraint priority pairs; 3-vs-2 cleanup threshold and exact-18th-birthday boundaries; half-open segment day-slots vs depot aggregate-capacity overlap; returnable-units and mile-pool conservation invariants. All formula-derived asserts are pre-computed literals.
- **§1.9**: 66 instances (55 active + 11 `excluded_because` stubs) across all nine guide sections, covering envelope shape, pagination, defaults, immutability, terminal lockdowns, idempotent re-fires, OCC stale/fresh sequence, RBAC denials, FK 404s, and both renewal happy-path (term rolls to 2028-08-01→2030-08-01) and denial paths.
- **Verification**: every setup/trigger chain was replayed against §1.2/§1.4/§1.6 (clock arithmetic checked per instance — sweeps suspend/reinstate at the intended points); all 9 rules × ≥2 instances; all error codes referenced; no forbidden concurrency vocabulary; `scaffold_lint.py` verdict: **clean lint** (43 endpoints, 10 entities, 18 + 55 instances, 723 calls scanned, FK reverse-reachability satisfied).

## Step 3: Copy Shared Files — 2026-08-14T15:15:00.000Z

Copied `./INSTRUCTION.md` to `tasks/task_1757_river_cleanup_adopt_roadway_program/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-14T15:29:00.000Z

PRD generated at `/home/ubuntu/github/CodingPRD/tasks/task_1757_river_cleanup_adopt_roadway_program/workspace/PRD.md`. The withheld design files were not opened or referenced.

**Document design** (domain-derived, not copied from the example):
- §1: three paragraphs from a business-context/pain-point angle.
- §2: 11 subsections — RBAC with per-role identity prose (ProgramCoordinator opaque; GroupLeader entity-backed by `AdopterGroup`), verbatim §2.2 envelope, pagination, resource identity/versioning (with the `DebrisReport` no-`updated_at`/no-`version` exception), the logical clock (startup default 2026-08-01T00:00:00Z, strictly forward, 4-sweep fixed order), the two compliance windows (ROLLING vs ANNIVERSARY), supply conservation, mileage conservation, OCC, precision/rounding, and a 10-family ordered validation sequence.
- §3: 8 subsections organized along the program timeline (groups/segments → agreements → events → waivers → supplies → debris/standing → hazards → signs/renewal/expiry), with all cascades spelled out link-by-link (suspension vs termination asymmetry on `BRIEFING_DONE`, completion-driven auto-reinstatement, sweep cascades), all calculation constants embedded in prose (365-day window, 180-day grace, 24-month term, 3-cleanup threshold, 14-day lead, 30-day report window, 90-day renewal window, per-bag weights 12.75/7.25/22.4/10.6/9.85, 2 bags/volunteer-mile, 1.25 water surcharge with the pinned double-rounding, worked 7-volunteer/2-mile example → 35 vs 28 bags), and every boundary inclusivity stated (exactly 3 qualifies; 18th birthday on signing day is not a minor; both-end-inclusive rolling/report/renewal windows; lower-inclusive/upper-exclusive anniversary windows; adjacent days allowed for day-slots).
- §4: 4-column table, 43 endpoints. §5: 2-column table, 43 errors. No audit footer.

**Hard Contract Reports**

```
Field coverage check:
- entities[].fields: 77 required (incl. id/created_at/updated_at/version), 77 present, 0 missing
- endpoints[].request_body/query_params identifiers: 12 additional required (decision, note, reason,
  expected_agreement_version, attendee_waiver_ids, returned_vests, returned_grabbers,
  mark_remaining_lost, to_iso8601, current_utc, limit, offset) plus material-line keys and
  metrics output keys — all present, 0 missing (89/89 total)
- enum/state literal tokens: 49 required, 49 present, 0 missing
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: 10 families (priorities 1-10) expressed as an explicit ordered
  sequence in §2.11, with per-endpoint relative ordering restated in §3.3/§3.6/§3.8, 0 missing
- concurrency_rules[] OCC rejections: 1 checked, 1 expressed (PATCH amendment +
  expected_agreement_version + ERR_STALE_VERSION/412, no race framing), 0 missing
- state_machines[].transitions: 24 checked, 24 fully expressed (from/to states, preconditions
  paired with error ids, side effects incl. all cascade links), 0 missing
- calculations[]: 7 checked, 7 fully expressed (compliance_standing both variants,
  official_event_weight both variants, supply_allocation, program_metrics, waiver_minor_age,
  returnables_conservation, mile_pool_conservation), 0 missing
- validations[] conditions: 43 checked, 43 matchable to error_id in §2/§3 prose, 0 missing
- endpoints[].side_effects / applies_to scopes: 43 endpoints checked, all expressed, 0 missing
- entities[].fields[] structured content: types/defaults/initial values/computed semantics
  reconstructible from prose, 0 missing
- sibling-branch symmetry: 8 groups checked (MEASURED/ESTIMATED, ROLLING/ANNIVERSARY,
  suspend/terminate cascades, postpone/no-show/cancel siblings, return-branch siblings,
  terminate-from-3-states, review/renewal decision pairs), all with equal prose density
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 383
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

All three hard contracts PASS.

## Step 5: Generate Unit Tests — 2026-08-14T16:04:00.000Z

All audits pass. The generation is complete.

## Summary

Generated complete test infrastructure and suite for `task_1757_river_cleanup_adopt_roadway_program` at `/home/ubuntu/github/CodingPRD/tasks/task_1757_river_cleanup_adopt_roadway_program/`.

**Stage 1 — `test_helpers/` (9 files):**
- `types.py` — 10 status/type enums + 12 entity TypedDicts; `DebrisReport` correctly carries only `id`/`created_at` (common_fields: false per PRD §2.4).
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD §4 endpoint (all 42, including `/_clock/set_current_utc`).
- `api_errors.py` — all 43 error IDs + HTTP status map, registered via `set_error_http_status_map`.
- `assertions.py` — per-entity validators plus `assert_depot_returnables_conserved` (PRD §2.7 invariant).
- `factories.py`, `constants.py` (per-bag weights 12.75/7.25/22.4/10.6/9.85, thresholds 3/365/180, clock default 2026-08-01), `test_users.py` (opaque coordinator + entity-backed `make_group_leader_headers(group_id)`), `fixtures.py` (composite helpers: active agreement, briefed/completed events, depots, clock sweeps), and the barrel `__init__.py`.

**Stage 2 — `test_suite/` (13 test files + `conftest.py`, 138 tests):**
- Queue A: all 18 difficulty instances covered by ≥2 tests each.
- Queue B: all 58 non-stub corner instances covered by ≥1 test; the 11 `excluded_because:` stubs were not translated (all cross-references verified to resolve).
- Every test's docstring carries a verbatim PRD citation (grep-verified with 8-word probes) and exactly one `Design: Difficulty/<rule_id>/<name>` or `Design: Corner/<section>/<name>` tag that resolves to a real instance. No skip/xfail markers anywhere; no "scaffold"/table references in comments.

**Notable PRD-adjudication decision:** the corner instance `program_metrics_status_filtering` asserted `adopted_miles == 2.0, available_miles == 1.5` for a setup containing a PENDING_REVIEW agreement on the 1.5-mile segment. PRD §2.8 explicitly states a segment is ADOPTED while its agreement is in PENDING_REVIEW, so a PRD-only implementer returns `adopted 3.5 / available 0.0`. The generated test asserts the PRD-derived values (3.5 / 0.0), not the design yaml's precomputed ones — PRD wins per the Core rule.

**Verification:** all 22 files parse, every test module imports against the real framework, and `pytest --collect-only` collects 138 tests with zero errors.

## Step 6: Generate Implementation — 2026-08-14T16:04:00.000Z

The implementation is complete and fully smoke-tested.

## Summary

Generated a complete Python + Flask implementation at `/home/ubuntu/github/CodingPRD/tasks/task_1757_river_cleanup_adopt_roadway_program/workspace/implementation/` covering all 43 endpoints (42 under `/program` + `POST /_clock/set_current_utc`).

**Files**: `start.sh` (guarded pip install, `exec python3 app.py`, `$PORT`/0.0.0.0, ~600ms cold boot), `requirements.txt` (flask only), `app.py`, `db.py` (empty in-memory store, no seeding), `errors.py` (all 42 catalog error IDs with exact HTTP statuses), `response.py` (meta/response_type/data envelope, pagination in meta), `middleware.py` (X-User-ID/X-User-Role auth, role checks, GroupLeader ownership chains), `util.py` (logical clock defaulting to 2026-08-01T00:00:00Z, strictly-forward, Decimal/ROUND_HALF_UP math, calendar month/year arithmetic), `validate.py`, plus `routes/` (12 blueprints) and `services/` (cascades, ROLLING/ANNIVERSARY compliance, 4 ordered clock sweeps).

**Key spec decisions** (cross-checked against SCAFFOLD_DIFFICULTY_DESIGN.yaml / SCAFFOLD_CORNER_DESIGN.yaml):
- Entity timestamps (`created_at`/`updated_at`, `signed_date`, `acknowledged_at`, etc.) stamp from the **logical clock**; envelope `meta.api_request_timestamp` is wall clock with 3 fractional digits. DebrisReport carries no `version`/`updated_at`.
- Validation families ordered per PRD §2.11: auth → role → existence → ownership → shape → state(+OCC) → safety → temporal → constraints → depot stock gate last.
- Segment status flips only on approval/terminate/expire/deny (two PENDING agreements may coexist on one segment; the second approval fails `ERR_SEGMENT_NOT_AVAILABLE`), matching the corner-design test over the entity-table prose.
- Rolling window [today−365d, today] both-inclusive; suspension sweep before expiry sweep so a non-compliant ACTIVE agreement suspends first; auto-reinstatement only on debris-report submission; renewal approve resets `standing` to NOT_EVALUATED explicitly while recomputing the counter.
- OCC accepts int or numeric-string `expected_agreement_version` (design files pass template-quoted values).

**Verification**: 4 smoke suites (140+ assertions) replayed every §1.8 difficulty instance and §1.9 corner instance over HTTP against fresh boots — all pass, including the suspend→reinstate cycle, rolling-window boundary, water-surcharge allocation (35 vs 28 bags), per-line-then-sum rounding (20.1), depot conservation invariants, OCC stale/fresh sequence, and the term-roll renewal (2028→2030) happy path.

## Step 7: Run Tests and Iterate — 2026-08-14T16:45:00.000Z

Clean 8-round parallel sweep achieved: all rounds 138/138, zero failures, zero errors.

## Summary

**Iterations run:** 2 (iteration 1: 6 deterministic failures in all 8 rounds; fixes applied; iteration 2: 8/8 rounds fully green).

**Tests deleted:** None. No test was deleted; two tests had individual non-uniquely-derivable assertions pruned per STEP 1b/1c while keeping every PRD-derivable assertion.

**Assertion prunes (unique-derivability collapse — PRD self-contradiction on segment status while PENDING_REVIEW):** PRD §2.8 sentence 2 + §3.2's clarification say a segment is `ADOPTED` while its agreement is `PENDING_REVIEW`; but §2.8 sentence 3 ("approval moves a segment from `AVAILABLE` to `ADOPTED`") + §3.2's approval-time `ERR_SEGMENT_NOT_AVAILABLE` double-approval catch require it to remain `AVAILABLE` until approval. Both readings are verbatim-supported, and the suite's passing `test_double_approval_caught_at_review_time` depends on the approval-time reading. The contested assertions went; the derivable ones stayed.
- `test_02_envelope_and_reads.py::test_program_metrics_status_filtering` — removed `adopted_miles == 3.5` / `available_miles == 0.0` (reading-dependent); replaced with the §2.8 conservation invariant `adopted_miles + available_miles == 3.5`, which holds under both readings. Kept `active_agreements`, `open_hazards`, `total_debris_lbs`, `completed_cleanups`.
- `test_03_agreements_lifecycle.py::test_rejected_agreement_segment_never_locked` — removed the mid-test `segment.status == "ADOPTED"` while PENDING_REVIEW; kept the reject→`AVAILABLE` assertion (derivable under both readings since REJECTED is terminal per §3.2).

**Fixes to `test_helpers/`:**
- `fixtures.py` / `setup_active_agreement` — added `contact_name` passthrough to `create_group` (PRD §3.1 group field); `test_08::test_debris_measured_vs_estimated_divergence` passed the kwarg and died with TypeError.

**Fixes to `test_suite/` (setup sequencing violating PRD preconditions — fixture/logic bugs, implementation was PRD-correct):**
- `test_05_compliance_standing.py::test_two_completions_fails_threshold_after_grace` — loop created the second event after advancing the clock to the first event's date, violating the §3.3 14-day lead (`ERR_EVENT_TOO_SOON`). Reordered: create+brief all events at the setup clock, then advance/complete.
- `test_05_compliance_standing.py::test_renewal_denied_when_first_anniversary_window_deficient` — `set_clock(2027-08-01)` with zero completions fired the mandatory §2.6 suspension sweep, cancelling the SCHEDULED events before briefing. Now briefs all events up front (BRIEFING_DONE is deliberately untouched by the §3.2 suspension cascade); the third completion auto-reinstates the agreement per §3.6, and renewal denial on the deficient first anniversary window still asserts `ERR_RENEWAL_NOT_ELIGIBLE`.
- `test_10_waivers.py::test_briefing_with_expired_waiver_rejected` — same sweep collision: the clock jump past waiver expiry suspended the zero-completion agreement and cancelled the target event (`ERR_EVENT_NOT_SCHEDULED` masked the intended check). Added three keepalive completions so the rolling count stays COMPLIANT; the briefing now reaches the PRD §3.3 expired-waiver branch and asserts `ERR_WAIVER_INVALID_ATTENDEE`. Also added the missing `complete_event` import.

**Fixes to `implementation/`:** None. The implementation was PRD-faithful on every contested path (suspension sweep, cascade semantics, segment status machine, OCC, rounding); all observed failures traced to test-side bugs or PRD ambiguity.

## Step 8: Finalize PRD — 2026-08-14T16:45:00.000Z

Done. `/home/ubuntu/github/CodingPRD/tasks/task_1757_river_cleanup_adopt_roadway_program/workspace/PRD_FINALIZED.md` is written with a minimal two-sentence patch.

## Line counts / delta
- `PRD.md`: 314 lines; `PRD_FINALIZED.md`: 314 lines — **0.0% line-count delta** (both edits are inline revisions within existing paragraphs; no sections added or removed).

## Changes (one bullet each)
- **§2.8 — revise —** sentence 2 of the mileage-conservation section: replaced "`AVAILABLE` while no non-terminal agreement spans it, and `ADOPTED` while an agreement referencing it is in `PENDING_REVIEW`, `ACTIVE`, `SUSPENDED`, or `RENEWAL_REVIEW`" with "`AVAILABLE` from creation and remains so while every agreement referencing it is `PENDING_REVIEW` or terminal, and `ADOPTED` while an agreement referencing it is in `ACTIVE`, `SUSPENDED`, or `RENEWAL_REVIEW`" — impl: `routes/segments.py:39`, `routes/agreements.py:72-89` (application never mutates segment), `routes/agreements.py:131` (flip only at approval).
- **§3.2 — revise —** application paragraph: removed `PENDING_REVIEW` from the set of agreement statuses that make a segment `ADOPTED`, and added that filing an application does not change segment status, so a second application on the same segment is accepted while the first awaits review, with the conflict caught only at approval time — impl: `routes/agreements.py:72-74` (only `status != "AVAILABLE"` gates creation) and `routes/agreements.py:128-130` (approval-time `ERR_SEGMENT_NOT_AVAILABLE` double-approval catch).

## Items from `<step_7_diff>` that required no PRD edit
- `fixtures.py` `contact_name` passthrough — pure test-helper bug; PRD §3.1 already pins `contact_name` and impl `routes/groups.py:24` requires it.
- `test_two_completions_fails_threshold_after_grace` — test setup violated the §3.3 14-day lead; impl `routes/events.py:111` is PRD-correct.
- `test_renewal_denied_when_first_anniversary_window_deficient` — test setup collided with the §2.6 suspension sweep; §2.6 sweep scope, §3.2 cascade (skips `BRIEFING_DONE`), and §3.6 auto-reinstatement already pin the impl behavior (`services/sweep.py:36-48`, `services/core.py:119-121`, `routes/events.py:356-359`).
- `test_briefing_with_expired_waiver_rejected` — §3.3 already pins expired-waiver `ERR_WAIVER_INVALID_ATTENDEE`; impl `routes/events.py:203-208` matches.

## Per-edit pre-edit search log
**Edit 1 (§2.8 segment status machine):**
- (a) Subject: `RoadSegment.status` — when a segment is `AVAILABLE` vs `ADOPTED`, and which operations transition it.
- (b) Paths enumerated (grep for `ADOPTED`/`PENDING_REVIEW` across all of `routes/` + `services/`, each file read): `routes/segments.py:19-42` (create → AVAILABLE), `routes/segments.py:64-72` (status filter), `routes/agreements.py:51-89` (application: refuses non-AVAILABLE only, no segment mutation), `routes/agreements.py:114-141` (approve requires AVAILABLE → flips ADOPTED; reject leaves segment untouched), `routes/agreements.py:183-196` + `services/core.py:115-121` (suspend cascade never touches segment — stays ADOPTED while SUSPENDED), `services/core.py:124-138` + `routes/agreements.py:199-211` (terminate frees segment), `routes/agreements.py:214-230` (renewal-request leaves segment — stays ADOPTED through RENEWAL_REVIEW), `routes/agreements.py:245-261` (renewal approve leaves segment; deny frees it), `services/sweep.py:50-56` (expiry sweep frees segment), `routes/metrics.py:19-22` (mileage summed by live status). All PRD sentences mentioning segment status (lines 119, 121, 152, 156, 158, 164, 212, 214, 216) checked for consistency.
- (c) Wording adjustment: used "remains so while every agreement referencing it is `PENDING_REVIEW` or terminal" rather than "no agreement spans it", so the clause stays consistent with the mixed-history path (a segment holding both a `TERMINATED` and an `ACTIVE` agreement must still read `ADOPTED`); sentence 3 (approval/termination/expiry/denial transitions) and the conservation paragraph kept verbatim since impl matches them exactly.

**Edit 2 (§3.2 application-time availability check):**
- (a) Subject: `ERR_SEGMENT_NOT_AVAILABLE` at application time and concurrent pending applications on one segment.
- (b) Paths enumerated: same set as Edit 1, focused on `routes/agreements.py:51-89` (`create_agreement`: role → reference → ownership → shape → single `segment["status"] != "AVAILABLE"` gate; no per-group/per-segment pending check) and `test_suite/test_03_agreements_lifecycle.py:230-247` (second concurrent application accepted; second approval rejected).
- (c) Wording adjustment: added "Filing an application does not itself change the segment's status … a second application on the same segment is accepted while the first awaits review, and the conflict between them is caught only at approval time"; deliberately did not specify whether the concurrent applicant may be the same group (impl allows it, but nothing requires pinning that tightly), and deferred the catch mechanics to §3.2's existing verbatim review-decision sentence, which already matches `agreements.py:124-130`.

## Step 9: Complete PRD — 2026-08-14T17:05:00.000Z

All changes verified. The work is complete. Here is the summary.

## Summary

**Source vs output:** `PRD_FINALIZED.md` (314 lines / 48,515 chars) → `PRD_COMPLETED.md` (317 lines / 52,087 chars). Delta: +3 lines, +3,572 chars, 22 diff hunks. No sections added; all changes are inline inserts/revisions.

**Counts:** 17 ambiguity-pin edits, 6 mismatch-revision edits (23 edit operations; some hunks absorbed two edits in the same paragraph).

**Ambiguity pins (PRD silent → pinned to impl):**
- §2.1 — insert — ambiguity — group record is its own chain root (leader fetches only own group); leader list results for agreements/events/waivers/supplies silently scoped to own chains, segment/hazard listings unscoped — `implementation/middleware.py:44-56`, `implementation/routes/helpers.py:35-55`, `implementation/routes/groups.py:37`
- §2.2 — revise — ambiguity — `api_request_id` pinned as `req_` + twenty random uppercase letters/digits — `implementation/util.py:21-23`
- §2.2 — insert — ambiguity — undeclared path or unsupported method → 404 `ERR_NOT_FOUND` — `implementation/app.py:29-35`
- §5 — insert — ambiguity — `ERR_NOT_FOUND` 404 row added to the error catalogue — `implementation/app.py:29-35`
- §2.3 — insert — ambiguity — non-integer/out-of-range `limit` (1–100) and negative/non-integer `offset` rejected with `ERR_INVALID_REQUEST` — `implementation/routes/helpers.py:11-32`
- §2.3 — revise — ambiguity — created_at ties broken by creation order; query filters are exact-equality, no-match yields empty page — `implementation/routes/helpers.py:46-51`, `implementation/db.py:21-27`
- §2.3 — insert — ambiguity — `has_more` = `offset` + returned items < `total_count` — `implementation/response.py:28`
- §2.4 — revise — ambiguity — `version` starts at 1 on creation — `implementation/services/core.py:18`
- §2.5 — revise — ambiguity — non-advancing clock rejected with `ERR_INVALID_REQUEST`; sub-second digits on `to_iso8601` discarded — `implementation/util.py:69-77`
- §2.6 — revise — ambiguity — sweep recompute covers agreements in `ACTIVE`/`SUSPENDED`/`RENEWAL_REVIEW`; auto-suspension acts only on `ACTIVE` agreements — `implementation/services/sweep.py:33-48`
- §2.9 — insert — ambiguity — `expected_agreement_version` accepts a JSON integer or a decimal string of digits — `implementation/routes/agreements.py:144-153`
- §2.10 — insert — ambiguity — month arithmetic (24-month term, 1-year waiver expiry, renewal roll) is calendrical with day clamped to target month's last day — `implementation/util.py:95-101`
- §3.1 — revise — ambiguity — `water_adjacent` filter accepts `true`/`false` (case-insensitive), other values → `ERR_INVALID_REQUEST` — `implementation/routes/segments.py:53-61`
- §3.2 — insert — ambiguity — null `special_instructions` on amendment clears the note — `implementation/routes/agreements.py:167,177-178`
- §3.3 — insert — ambiguity — empty `attendee_waiver_ids` list rejected with `ERR_WAIVER_INVALID_ATTENDEE` — `implementation/routes/events.py:201-202`
- §3.4 — revise — ambiguity — guardian/consent/supervisor fields supplied on an adult waiver are discarded (nulls + consent false) — `implementation/routes/waivers.py:74-77`
- §3.5 — insert — ambiguity — `returned_vests`/`returned_grabbers` both required non-negative integers; every accepted return refreshes depot `version`/`updated_at` even when no units move — `implementation/routes/supplies.py:57-58,92-93`
- §3.6 — insert — ambiguity — `bag_count` non-negative integer, `line_weight_lbs` non-negative number — `implementation/routes/events.py:270-277`
- §3.6 — insert — ambiguity — report object shape pinned: carries `event_id`, echoes `weight_method`/`material_lines`, stores `measured_total_weight_lbs` as 1dp scale reading (null under ESTIMATED) — `implementation/routes/events.py:335-345`
- §3.7 — insert — ambiguity — `agency_reference` format pinned: `AGY-` + twelve uppercase hex chars — `implementation/routes/hazards.py:97`

**Mismatch revisions (PRD contradicted impl → revised to impl):**
- §2.4 — revise — mismatch — `created_at`/`updated_at` are whole-second logical-clock stamps (`YYYY-MM-DDTHH:MM:SSZ`, no fractional digits), not "three fractional digits"; envelope `api_request_timestamp` keeps the 3-fractional-digit wall-clock form — `implementation/util.py:50-64`, `implementation/services/core.py:12-20` (verified live: `created_at: "2026-08-01T00:00:00Z"`)
- §3.2 — revise — mismatch — termination from `PENDING_REVIEW` also refused with `ERR_AGREEMENT_TERMINAL`, not only from terminal states — `implementation/routes/agreements.py:206-207` (verified live)
- §3.3 — revise — mismatch — briefing check enumeration reordered: listed waivers resolve (family 3) before the `SCHEDULED` state guard (family 6), matching §2.11 — `implementation/routes/events.py:194-198`
- §3.3 — revise — mismatch — event PATCH: `SCHEDULED` events also accept a new `scheduled_date` (same lead-time/day-slot checks, stays `SCHEDULED`); `POSTPONED` accepts plain edits with or without a date; edits on `BRIEFING_DONE` draw `ERR_EVENT_TERMINAL` — `implementation/routes/events.py:152-181` (verified live)
- §3.6 — revise — mismatch — MEASURED reconciliation rounds each line half-up to 1dp first, sums the rounded lines, and compares to the 1dp-rounded measured total; official weight is the scale reading at one decimal — `implementation/routes/events.py:321-334`
- §4 — revise — mismatch — PATCH `/program/events/{id}` table description updated to match the revised §3.3 edit semantics — `implementation/routes/events.py:152-181`

Everything else in the implementation (all 43 endpoints, role tables, state machines, cascades, supply/mileage conservation, allocation formula and worked example, compliance windows, error taxonomy and HTTP statuses, sweep order) was already uniquely pinned by the PRD and left untouched.
