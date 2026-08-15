# Worklog — task_1392_closed_captioning_audio_description

## Step 1: Create Task Directory — 2026-08-13T03:22:00.000Z

Directory `tasks/task_1392_closed_captioning_audio_description/` and `workspace/` pre-created and pre-assigned by the pipeline launcher (Step 1 treated as DONE per invocation args). User directive: difficulty harder than expert level.

## Step 2: Generate Scaffold — 2026-08-13T04:44:48.000Z

All three artifacts are generated and lint-clean. Final lint verdict (verbatim):

```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
  §1.5 endpoints declared: 88 | §1.1 entities: 12 | §1.8 instances: 18 | §1.9 instances: 62 | calls scanned: 1052
```

## Summary

**Files written** (task dir: `/home/ubuntu/github/CodingPRD/tasks/task_1392_closed_captioning_audio_description/`):
- `SCAFFOLD.yaml` (2008 lines) — §1.0–§1.7 only
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (1600 lines) — single key `scaffold_difficulty_design`
- `SCAFFOLD_CORNER_DESIGN.yaml` (3752 lines) — single key `scaffold_corner_design`

**Counts**: 12 entities · 10 state machines · 10 calculations · 11 validation priorities · 88 endpoints · 33 error codes · 8 roles · 3 OCC concurrency rules. §1.8: 18 instances (exactly 2 per rule across all 9 rules). §1.9: 62 instances — entities 9, state_machines 15, calculations 8, validations 14, endpoints 2, errors 7 (all stubs), rbac 4, cross_cutting_layers 10 (incl. 1 stub), consistency_model 1; 54 executable + 8 `excluded_because` stubs.

**Difficulty design highlights** (harder-than-expert per directive): dual-variant SLA clock basis (business vs wall hours) and full-vs-sampled QC accuracy; combinatorial formulas in modes (c) quote-evaluation-order and (b) nested per-gap rounding; QC rework cycle with hidden 3-fail terminal absorption and complaint resolve→reopen cycle; depth-4 complaint cascade (track→archive freeze→work-order remediation→conversion cancel) and depth-3 preemption→posture-drop→auto-reoffer cascade; priority conflicts state-vs-constraint and temporal-vs-referential; boundary straddles on accuracy rounding (98.995→99.00 pass vs 98.994 fail, exact-decimal pinned) and committed-minutes cap (300 ok / 301 reject); cross-entity gates (confirm×media, conversion×track); two interval geometries (half-open buffered stenographer occupancy vs closed 30-min-min-gap studio bookings); compensating invariants on capacity-minutes and current-version cardinality.

**Adjudicated design decisions**:
1. **Validation ordering**: placed existence (p3) before ownership (p4) and shape (p5) after a mid-design conflict between complaint subject-cardinality (shape) and FK existence; the two-subject corner uses existing rows so the shape rule is the one under test.
2. **ERR_GO_ON_AIR_BLOCKED reachability**: go-on-air accepts from {SCHEDULED, BRIEFED} so the zero-CONFIRMED guard is reachable (otherwise the auto BRIEFED→SCHEDULED drop would make it dead).
3. **Removed ERR_DELIVERY_INCOMPLETE / ERR_MAX_QC_ATTEMPTS_REACHED**: both were shadowed by ERR_INVALID_TRANSITION (ready-gate is a pure state gate; third QC fail lands terminal).
4. **Cascade attribution**: conversion-job cancellation is caused by the work order entering REMEDIATION (not the track dispute) to keep the Rule-4 depth-4 chain honest.
5. **Retention clock**: rearchive never recomputes `archived_at`/`purge_after` — pinned once at first cold-store.
6. **Reopen re-disputes the remediation artifact** (not the SUPERSEDED original) — patched into the complaint machine.
7. All formula-derived assert literals were computed by executing the formulas in Python (quotes 55969/43500/43750/25500/24975/44250/54000; accuracy 99.00/98.99/95.10/93.55; coverage 35.0/85.0/86.0; SLA due_at values incl. weekend rollover; retention dates) — zero unresolved expressions.

No sibling task directories were inspected at any point.

## Step 3: Copy Shared Files — 2026-08-13T04:45:30.000Z

Copied `./INSTRUCTION.md` → `tasks/task_1392_closed_captioning_audio_description/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-13T04:54:00.000Z

88 endpoint rows and 33 error rows (35 minus header and separator) — both match exactly. All three hard contracts pass.

## Summary

**Output**: `/home/ubuntu/github/CodingPRD/tasks/task_1392_closed_captioning_audio_description/workspace/PRD.md` — 339 lines.

**Section list**:
- §1 Introduction
- §2 Global Specifications & System-Wide Principles: 2.1 RBAC · 2.2 API Response Structure (verbatim) · 2.3 Pagination · 2.4 Resource Identity and Mutation Semantics · 2.5 Optimistic Concurrency Control · 2.6 Precision and Rounding · 2.7 The Logical Clock and the Operations Sweep · 2.8 Turnaround Tiers and Compliance Standards · 2.9 Segregation of Duties
- §3 Business Logic & Workflows: 3.1 Client Administration and Media Intake · 3.2 Work Orders (Quoting/Confirmation/SLA) · 3.3 Caption Track Authoring and Versioning · 3.4 Accuracy QC and Compliance Thresholds · 3.5 Audio Description (Gaps/Scripts/Studio) · 3.6 Live Events and the Stenographer Roster · 3.7 Offers/Check-In/Preemption/Air Control · 3.8 Error Complaints and Remediation · 3.9 Format Conversion and the Archive
- §4 Endpoint Definitions (88 rows, 4 columns)
- §5 Error Code Catalogue (33 rows, 2 columns)

**Entity/rule coverage confirmation** — all from `SCAFFOLD.yaml` appear in prose:
- 12 entities (Client, MediaAsset, WorkOrder, CaptionTrack, QCReview, AudioDescriptionTrack, LiveEvent, Stenographer, LiveAssignment, Complaint, ConversionJob, ArchiveItem) with every field named verbatim.
- 9 state machines with every transition pair expressed with both states named in the same clause (verified via windowed search; several sentences were tightened to make from→to pairs explicit, e.g., stenographer suspend/reinstate/renew, complaint resolve/reopen/triage, conversion internal legs, delivery cascade on tracks).
- 10 calculations fully narrated: sla_turnaround_window (tier brackets + business vs wall clock), work_order_quote (pinned 5-step order, multiplier before discount), caption_accuracy (weights 1/3/10, per-mode denominators, ROUND_HALF_UP 2dp single rounding, inclusive threshold, 98.995→99.00 example), ad_gap_coverage (per-gap-first pinned rounding, [35.0, 85.0] inclusive), stenographer_committed_minutes (UTC-day, inclusive cap, conservation invariant), stenographer_overlap_window (half-open, asymmetric buffers, touching edges allowed), studio_booking_window (closed intervals, 30-minute turnover, self re-booking exemption), archive_purge_eligibility (2555/1095/90 days, pinned archived_at, inclusive purge_after), complaint_escalation (24/48/72h, inclusive, updated_at refresh, reopen +1), auto_offer_selector (7 pool predicates, 3-key ranking, empty-pool split by trigger).
- 11 validation priority levels expressed as an explicit evaluation ordering in §2.4, with conditions and error IDs scattered to their workflow homes.
- 3 OCC rules each naming write endpoint, `expected_<parent>_version`, mismatch rejection, exact error ID, and HTTP 412.
- 88 endpoints in §4 (4 columns), 33 errors in §5 (2 columns), all 8 roles with identity prose in §2.1.

**Hard-contract reports**:
- Contract 1 (Field-Name Coverage): 123 required, 123 present, 0 missing. PASS
- Contract 2 (Rule Coverage): all 11 validations (incl. priority), 3 OCC rules, 9 state machines (all transitions), 10 calculations, 33 error IDs in §2/§3 prose, 88 endpoint side-effect sets, structured field content. PASS
- Contract 3 (§3 Path Purity): 726 backtick tokens scanned in §3; 0 starting with `/`, 0 bare HTTP methods, 0 method+path combos. PASS
- §2.2 matches the canonical block byte-for-byte (verified via diff).

**Zero-Silence Rule adjudications** (rules the scaffold implies but does not state literally, where I had to make a judgment call in prose):

1. **Complaint re-dispute on reopen targets the remediation track when set** — scaffold side_effect says "the complaint's current artifact (the remediation track when remediation_track_id is set, else the original subject track) DELIVERED -> DISPUTED". I rendered this verbatim in §3.8 and did not invent a separate track-status rule.
2. **Live-event complaint creation window uses `end_at`** — scaffold validation names "live events: event end_at" as the complaint window anchor; I kept this phrasing in §3.8 without extending it to `SETTLED`-specific timestamps.
3. **Auto-offer on no-show** — scaffold explicitly says "no auto-offer on no-show" (unlike preempt). I preserved the asymmetry ("unlike preemption — no auto-offer cascade runs") rather than smoothing it over.
4. **`PREEMPTED`/`CANCELLED` release committed minutes but only `PREEMPTED` credits make-up minutes** — scaffold is explicit; I rendered both sides symmetrically in §3.7.
5. **Remediation AD track does not version** — scaffold notes AD remediation "reopens the same track; no new version". I surfaced this as "One asymmetry matters: AD remediation does not version."
6. **`READY_FOR_DELIVERY` recompute on both caption mark-conformed and AD approve-mix** — I used identical phrasing ("the same work-order coverage recompute") for the AD side to enforce sibling-branch symmetry.
7. **Conversion `VALIDATING`/`CONVERTING` are non-resting** — scaffold marks both with `note: "not an externally observable rest state"`. I rendered this as "without resting in either intermediate state" and still named the internal legs explicitly so the from→to chain is complete.

No sibling tasks were consulted; neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened, grepped, or referenced.

## Step 5: Generate Unit Tests — 2026-08-13T05:26:00.000Z

Generation complete and verified. Final summary:

## Task 1392 — test infrastructure generated

**test_helpers/** (9 files, `/home/ubuntu/github/CodingPRD/tasks/task_1392_closed_captioning_audio_description/test_helpers/`):
`__init__.py` (barrel), `types.py` (10 entity TypedDicts + 12 status/role enums; QCReview correctly omits `updated_at`/`version`), `api_client.py` (64 endpoint methods, one per PRD §4 row), `api_errors.py` (33 error IDs + HTTP map registered via `set_error_http_status_map`), `assertions.py` (per-entity asserts + `parse_instant`/`assert_same_instant`), `factories.py`, `constants.py`, `test_users.py` (TEST_USERS + `make_client_headers`/`make_stenographer_headers` for the two entity-backed roles), `fixtures.py` (composite setups: in-production orders, QC queue, delivered orders, AD-to-RECORDING, accepted/confirmed/settled live events, open complaints, `remediate_and_redeliver` + `resolve_complaint` split so callers pin the resolve instant).

**test_suite/** (`.../test_suite/`): `conftest.py` + 8 test files, **100 tests, all collected cleanly by pytest** (PYTHONPATH=task dir).

**Coverage verdicts (audited programmatically):**
- Queue A (Difficulty): 18/18 instances, ≥2 tests each — 38 tests total.
- Queue B (Corner): 62/62 non-stub instances, ≥1 test each — 62 tests. All 8 `excluded_because:` stubs (7 errors-section + `ytd_reconciles_on_deliver`) correctly untranslated; their cross-references resolve.
- Every docstring ends with exactly one `Design:` line resolving to a real instance (0 untagged/dual-tagged/mismatched).
- Every quoted PRD citation survives a literal whitespace-normalized grep of PRD.md (0 failures).
- No `skip`/`skipif`/`xfail` markers; no scaffold references in comments/docstrings.

**Instances skipped: none.** Two instances were translated with narrowed assertions where PRD is silent on a sub-claim (silence-pattern rules):
- `Corner/entities/client_creation_defaults_applied` — asserts `client_status == ACTIVE` and `ytd_completed_minutes == 0` (PRD §3.1 verbatim); the `default_turnaround_tier == STANDARD` sub-claim was dropped because PRD names no server-side default for the omitted field (default-value silence).
- `Corner/entities/qc_review_immutable_shape` — asserts the immutable-record shape (PRD §2.4 verbatim) and scoring; the "no PATCH endpoint exists" sub-claim was dropped (route-absence behavior is not uniquely derivable).

Notable faithful translations: both priority-pair tests rely on PRD §2.4's verbatim fixed validation ordering; all pre-computed literals from the design indices (due_at 2026-08-11T10:00:00Z vs 2026-08-04T16:00:00Z, quote 55969, accuracy 95.10/93.55, 98.995→99.00 PASS vs 98.994→98.99 FAIL, capacity 300/301, booked_minutes 280/20/80, purge boundaries) were carried verbatim into assertions with instant-tolerant timestamp comparison.

## Step 6: Generate Implementation — 2026-08-13T05:26:30.000Z

Implementation complete. Summary:

## Files (all under `/home/ubuntu/github/CodingPRD/tasks/task_1392_closed_captioning_audio_description/workspace/implementation/`)

| File | Lines |
|---|---|
| start.sh | 10 |
| requirements.txt | 1 |
| app.py | 43 |
| db.py | 71 |
| errors.py | 61 |
| respond.py | 84 |
| auth.py | 68 |
| util.py | 96 |
| serialize.py | 239 |
| services/__init__.py | 0 |
| services/pricing.py | 103 |
| services/qc.py | 70 |
| services/ad.py | 91 |
| services/livelog.py | 99 |
| services/workflow.py | 376 |
| routes/__init__.py | 35 |
| routes/clients.py | 83 |
| routes/media.py | 105 |
| routes/work_orders.py | 231 |
| routes/caption_tracks.py | 227 |
| routes/ad_tracks.py | 241 |
| routes/live_events.py | 151 |
| routes/stenographers.py | 101 |
| routes/assignments.py | 208 |
| routes/complaints.py | 295 |
| routes/conversions.py | 129 |
| routes/archive.py | 129 |
| routes/ops.py | 25 |

Total 3372 lines, 27 files.

## Endpoint coverage: 88/88
Route decorator count matches the PRD §4 table exactly (88), including the two ops endpoints (`_clock/set_current_utc`, `_ops/run-sweep`).

## Coverage confirmation
- **State machines (9)**: MediaAsset intake, WorkOrder (incl. QUOTE_EXPIRED/REMEDIATION loops), CaptionTrack (cyclic QC rework, third-FAIL → QC_FAILED_PERMANENT terminal lockdown), ADTrack (incl. non-versioning AD remediation DISPUTED→SCRIPTING), LiveEvent (BRIEFED⇄SCHEDULED posture), Stenographer, LiveAssignment (full offer/preempt/no-show lifecycle), Complaint (incl. REOPENED loop), ConversionJob (atomic QUEUED→…→COMPLETED/FAILED_VALIDATION pass), ArchiveItem (pinned retention clock, rearchive non-recompute).
- **Calculations (9)**: work_order_quote (pinned multiplier-before-discount order, Decimal ROUND_HALF_UP — verified 16496-cent pin), sla_turnaround_window (business-hours Mon–Fri 09:00–17:00 UTC for STANDARD/EXPRESS vs wall-clock RUSH/SAME_DAY — verified Sat-confirm 120bh → Fri 17:00 pin), caption_accuracy (exact decimal, single final rounding, 98.995→99.00 inclusive-threshold PASS pin), ad_gap_coverage (per-gap-then-mean pinned rounding, 34.85/34.95/34.95→35.0 pass pin), stenographer_committed_minutes (inclusive cap), stenographer_overlap_window (half-open asymmetric buffers, touching edges allowed), studio_booking_window (closed intervals, exact 30-min turnover), archive_purge_eligibility (inclusive purge_after, prose-order gates), complaint_escalation (inclusive hour thresholds, updated_at refresh), auto_offer_selector (full pool filters incl. exclusion memory, committed/certified_since/created_at ranking).
- **Validations**: enforced in PRD §2.4 priority order (auth → role → existence L-to-R → ownership → shape → OCC → state → SoD/compliance → temporal → capacity/geometry → linked-entity state). One deliberate ordering decision: accept-delivery checks `active_complaint_count` (ERR_COMPLAINTS_STILL_OPEN) before the DELIVERED from-state, because the complaint cascade moves the order to REMEDIATION and a state-first check would permanently mask the catalogued error the scaffold pins on this endpoint.
- **Errors**: all 33 catalogue error IDs with exact HTTP statuses; OCC uses `expected_work_order_version`/`expected_live_event_version` with 412s; QCReview serialized without `updated_at`/`version` per PRD §2.4.
- **Storage**: in-memory dicts only, zero seeding at startup, logical clock defaults to 2026-08-01T00:00:00Z and never falls back to wall clock.

## start.sh contract
`cd "$(dirname "$0")"`, guarded dependency install (`if ! python3 -c "import flask"`), `exec python3 app.py` in foreground; app binds `0.0.0.0` on `PORT` (default 10000).

## Smoke result
Booted via `bash start.sh` on a fresh process (empty store confirmed), ran three end-to-end suites against it — full caption/QC/deliver/complaint/archive pipeline, quote/SLA numeric pins, QC fail loop, remediation+reopen loop, conversion retry limits, AD studio geometry, live selector/decline/preempt/no-show cascades, sweeps, pagination — all checks passed (final contract check: POST /clients → 201 with correct envelope, then killed cleanly). No sibling tasks or test_helpers/test_suite were touched.

## Step 7: Run Tests and Iterate — 2026-08-13T05:39:00.000Z

All 8 rounds pass 100/100 — the loop exits clean. Final summary:

## Summary

**Iterations run:** 2 (sweep 1: 90/100 × 8 rounds with an identical deterministic failure set; sweep 2 after fixes: 100/100 × 8 rounds, 800/800 total).

**Tests deleted:** none. Every failing test asserted a rule verbatim-covered and uniquely derivable from PRD.md — all failures were test-layer bugs, not PRD-silence or unique-derivability collapses.

**Fixes applied to `test_helpers/`** (1 file, 7-test reach):
- `/home/ubuntu/github/CodingPRD/tasks/task_1392_closed_captioning_audio_description/test_helpers/fixtures.py` — `setup_open_complaint()` gained a `description="caption error"` parameter forwarded to `file_complaint`. Previously the kwarg fell into `**order_overrides` and crashed `setup_in_production_order` with `TypeError`, taking down all 7 test_06 tests that file complaints with explicit descriptions (PRD §3.8 declares `description` as a complaint body field; the fixture simply failed to forward it).

**Fixes applied to `test_suite/`** (3 files, 3 tests):
- `test_02_work_orders_quoting.py::test_express_friday_confirm_rolls_over_weekend` — moved `set_clock("2026-08-07T16:00:00Z")` ahead of `quote_order`. The test quoted at the default clock (2026-08-01) then confirmed on 2026-08-07, so the 72-hour quote expiry (PRD §3.2) had legitimately lapsed and `ERR_QUOTE_EXPIRED` was correct server behavior. The weekend-rollover assertion (`due_at` = 2026-08-17T16:00:00Z) is unchanged and verified.
- `test_03_caption_tracks_qc.py::test_third_fail_is_terminal_and_rework_rejected` — FAIL #1 now calls `finalize_qc` directly instead of `_drive_fail` (submit+enqueue), because the `setup_track_in_qc_queue` fixture already leaves the track QC_QUEUED; re-submitting violated the PRD §3.3 state machine. Matches the sibling two-cycle test's pattern.
- `test_05_live_operations.py::test_released_capacity_is_immediately_reusable` — added a clock rewind to 08:00 before creating the 09:50-start event. With the clock at 14:00, `offer_expires_at = min(offered+4h, start_at)` (PRD §3.7) made the offer born expired, so accept correctly raised `ERR_OFFER_EXPIRED`. The discriminating assertion (E4 overlaps preempted E1's freed occupancy window) is preserved.

**Fixes applied to `implementation/`:** none. Every PRD-required server check implicated by the failures (72h quote expiry, caption-track state-machine admissibility, offer-expiry rejection) was behaving correctly; the bugs were all in the test layer.

## Step 8: Finalize PRD — 2026-08-13T05:42:00.000Z

Done. PRD_FINALIZED.md produced at `/home/ubuntu/github/CodingPRD/tasks/task_1392_closed_captioning_audio_description/workspace/PRD_FINALIZED.md` as a verbatim copy of PRD.md with **0 changes**.

**Line counts / %-delta:** PRD.md = 337 lines; PRD_FINALIZED.md = 337 lines; delta 0.0%.

**Changes:** none — zero edits, so there is no per-edit search log. Per-item adjudication below; for each item I verified the rule is verbatim-covered in PRD.md and that the implementation matches the PRD (so no PRD-mismatch exists either).

**Per-item adjudication (why each Step 7 diff item required no PRD change):**

1. **`test_helpers/fixtures.py` — `setup_open_complaint()` `description` forwarding (fixture bug).**
   - (a) Subject: complaint creation body field `description`.
   - (b) Paths enumerated: `implementation/routes/complaints.py:114-116` (requires `description` be a non-empty string, else `ERR_VALIDATION`), field stored at line 134; PRD §3.8 (line 180): "The complaint body carries a `severity` of `FCC_CRITICAL`, `MAJOR`, or `MINOR` and a free-text `description`."
   - (c) The failure was a `TypeError` in the fixture before any server call — the PRD already declares the field and the impl already accepts/stores it. Pure test-layer bug; no PRD silence revealed at the Step 7 site.

2. **`test_02` — quote-then-confirm across the 72h expiry (test-clock bug).**
   - (a) Subject: 72-hour quote expiry and confirm rejection at/after `quote_expires_at`.
   - (b) Paths enumerated: `implementation/routes/work_orders.py:120` (`quote_expires_at = now() + timedelta(hours=72)`), `:137-138` (confirm at/after expiry → `ERR_QUOTE_EXPIRED` 409), `:178` (amendment re-sets the 72h window), `implementation/services/workflow.py:333` (sweep expires `QUOTED` → `QUOTE_EXPIRED`); PRD §3.2 (lines 120, 122, 126) covers all of these verbatim, including HTTP 409.
   - (c) Server behavior was correct; the test let a real expiry lapse. PRD already uniquely determines the behavior.

3. **`test_03` — re-submitting a `QC_QUEUED` track (test state-machine violation).**
   - (a) Subject: caption-track submit-review admissible source states.
   - (b) Paths enumerated: `implementation/routes/caption_tracks.py:115` (`submit_review` transitions only from `{"AUTHORING"}` → `INTERNAL_REVIEW`), `:121` (return-to-authoring from `INTERNAL_REVIEW`), `:127` (enqueue-qc from `INTERNAL_REVIEW`), `:165-166` (QC finalize only from `QC_QUEUED`); PRD §3.3 (line 134): "Submitting moves `AUTHORING` → `INTERNAL_REVIEW`" — the state machine is pinned and submitting from `QC_QUEUED` is inadmissible per the PRD.
   - (c) Fixture already left the track `QC_QUEUED`; the fixed test calls `finalize_qc` directly, matching the PRD state machine the impl enforces.

4. **`test_05` — offer born expired (`min(offered+4h, start_at)`) then accepted (test-clock bug).**
   - (a) Subject: `offer_expires_at` computation and accept rejection at/after expiry.
   - (b) Paths enumerated: `implementation/services/workflow.py:281` (`offer_expires_at = min(t + timedelta(hours=4), event["start_at"])`), `implementation/routes/assignments.py:118-119` (accept at/after → `ERR_OFFER_EXPIRED` 409), `implementation/services/workflow.py:328` (sweep expires `OFFERED` → `OFFER_EXPIRED`); PRD §3.7 (lines 162, 168, 170) covers all three verbatim, including the "earlier of four hours after `offered_at` and the event's `start_at`" formula and HTTP 409.
   - (c) Server behavior was correct; the test created an event whose start was under 4h out with the clock already past start. PRD already uniquely determines the behavior.

No edits were committed, so the NO-NEW-MISMATCH pre-edit search produced no wording to validate; the enumerations above double as confirmation that PRD prose and implementation agree at every path touching each item's subject.

## Step 9: Complete PRD — 2026-08-13T06:08:00.000Z

Done. `PRD_COMPLETED.md` is written at `/home/ubuntu/github/CodingPRD/tasks/task_1392_closed_captioning_audio_description/workspace/PRD_COMPLETED.md` — a pure in-place patch over `PRD_FINALIZED.md` (which is byte-identical to `PRD.md`). Only this one file was created/modified; nothing outside `workspace/` was touched, and SCAFFOLD*.yaml / worklog.md were not read.

**Size**: PRD_FINALIZED.md 337 lines / 57,507 chars → PRD_COMPLETED.md 337 lines / 61,032 chars (**+3,525 chars**). 30 existing lines revised in place; no lines added/removed; no new sections.

**Counts**: 35 ambiguity-pins, 2 mismatch-revisions (37 discrete changes across 30 lines).

Changes (section — insert|revise — kind — what — impl evidence):

- §2.2 — insert — ambiguity — `api_request_timestamp` reads the logical clock — implementation/respond.py:14 (`fmt_dt(now())`, `now()` is the logical clock, db.py:28)
- §2.3 — revise — ambiguity — non-integer/out-of-range `limit`, negative `offset` → `ERR_VALIDATION` (400); list ties on `created_at` broken by creation order — respond.py:46-78
- §2.4 — revise — ambiguity — `version` starts at 1 on creation — db.py:62 (`stamp_new`)
- §2.7 — revise — ambiguity — archive sweep keys on the work order's `delivered_at` (tracks carry none) — services/workflow.py:360-370
- §3.1 — insert — ambiguity — omitted `default_turnaround_tier` defaults to `STANDARD` — routes/clients.py:30
- §3.1 — insert — ambiguity — quoting an order on a `REJECTED_INTAKE` asset → `ERR_INVALID_TRANSITION` (409) — routes/work_orders.py:114-115
- §3.2 — revise — ambiguity — `language` accepted as any non-empty string (no BCP-47 validation); no client↔media cross-ownership check at creation — work_orders.py:56-64
- §3.2 — insert — ambiguity — confirm checks fire in fixed order: from-state → quote expiry → client-active → media-cleared — work_orders.py:133-144
- §3.2 — insert — ambiguity — accept-delivery evaluates the complaint-count check (`ERR_COMPLAINTS_STILL_OPEN`) before the `DELIVERED` from-state check — work_orders.py:210-217
- §3.2 — revise — **mismatch** — QUEUED conversion-job cancellation happens on complaint **filing** only; a **reopen does not** re-run it — workflow.py:159-184 (`dispute_cascade`) vs complaints.py:281-294 (reopen has no cancel call)
- §3.2 — insert — ambiguity — each delivery re-applies the full fan-out, so re-delivery after remediation grows `ytd_completed_minutes` again — workflow.py:122-142
- §3.3 — revise — ambiguity — track `language` any non-empty string; `supersedes_track_id` stored verbatim, not FK-resolved (no `ERR_NOT_FOUND`) — caption_tracks.py:41, 47-49
- §3.3 — revise — ambiguity — track archive sweep keyed on the work order's `delivered_at` — workflow.py:364
- §3.4 — insert — ambiguity — under `FULL_REVIEW`, `sampled_words` may be omitted/null; if supplied must be an integer, is stored, and plays no role in scoring — services/qc.py:49-50, caption_tracks.py:179
- §3.5 — insert — ambiguity — AD track creation takes no OCC field and does not increment the work order's `version` — routes/ad_tracks.py:38-70
- §3.5 — insert — ambiguity — AD edit is partial (omitted/null fields unchanged); editing while not `SCRIPTING` → `ERR_INVALID_TRANSITION` — ad_tracks.py:90-118
- §3.5 — insert — ambiguity — script rejection requires a non-empty `rejection_note` — ad_tracks.py:160-162
- §3.5 — insert — ambiguity — submit-mix without a booking, or before `record_end_at` → `ERR_INVALID_TRANSITION` (409) — ad_tracks.py:202-205
- §3.5 — insert — ambiguity — mix rejection requires a non-empty `rejection_note` — ad_tracks.py:230-232
- §3.6 — insert — ambiguity — supplied `max_daily_live_minutes` must be an integer ≥ 1 — routes/stenographers.py:33
- §3.6 — insert — ambiguity — renewal with a new expiry not later than now → `ERR_INVALID_TRANSITION` (409) — stenographers.py:96-97
- §3.7 — insert — ambiguity — offer creation admitted regardless of the event's status — routes/assignments.py:40-43 (no status check)
- §3.7 — insert — ambiguity — selector ranking: ties beyond `created_at` broken by roster creation order — services/livelog.py:98
- §3.7 — revise — ambiguity — the selector runs on **every** preemption; the `BRIEFED`→`SCHEDULED` fallback is gated separately on no remaining `CONFIRMED` — assignments.py:185-188
- §3.7 — insert — ambiguity — no-show marked before `start_at` → `ERR_INVALID_TRANSITION` (409) — assignments.py:199-200
- §3.7 — insert — ambiguity — wrap before `end_at` → `ERR_INVALID_TRANSITION` (409) — routes/live_events.py:116-117
- §3.8 — revise — ambiguity — complaint `client_id` is derived from the subject (a body `client_id` is ignored); ineligible subject state → `ERR_INVALID_TRANSITION` (409) — complaints.py:99-106, 126-129
- §3.8 — insert — ambiguity — filing moves the order to `REMEDIATION` only when currently `DELIVERED`; a `CLIENT_ACCEPTED` order stays `CLIENT_ACCEPTED` while the complaint counts against it — workflow.py:181-183
- §3.8 — insert — ambiguity — remediation caption track inherits the disputed track's `language`, `caption_format`, `speaker_id_style` — workflow.py:230-232
- §3.8 — insert — ambiguity — resolving a caption complaint clears `dispute_freeze` on both the remediation track's and the original disputed track's archive items; track-subject resolve checks fire state → SoD → artifact-DELIVERED — complaints.py:239-260
- §3.8 — insert — ambiguity — reopen's track/order transitions apply only when each record sits in the named from-state; `dispute_freeze` is re-applied regardless — complaints.py:284-294
- §3.9 — insert — ambiguity — conversion create fires the same-format and embed checks before the source-track state check — routes/conversions.py:43-49
- §3.9 — insert — ambiguity — `output_duration_ms` is a required integer — conversions.py:85-88
- §3.9 — revise — **mismatch** — automatic cancellation is per-order on complaint filing ("every QUEUED job whose source track belongs to the order"); a reopen that re-disputes a track does not cancel jobs — workflow.py:147-156 + complaints.py:281-294
- §3.9 — revise — ambiguity — one archive item per delivered track **per delivery** (a re-delivered AD remediation track gets a fresh item) — workflow.py:135, 140
- §3.9 — insert — ambiguity — set-legal-hold takes a boolean `legal_hold` body field and applies in any archive status — routes/archive.py:123-129
- §4 — revise — ambiguity — complaints list is also filterable by `client_id` — complaints.py:150-162

The two true mismatches both concern reopen: the PRD's "entering remediation also cancels every QUEUED conversion job" (§3.2) and "cancels QUEUED jobs automatically when their source track becomes DISPUTED" (§3.9) both contradict the implementation, which cancels only during the filing-time `dispute_cascade` and never on reopen. Everything else the implementation did was already uniquely pinned by the PRD (pricing/SLA math, accuracy scoring, gap coverage, studio/overlap/capacity geometry, sweep rules, OCC placement, envelope shape) and was left untouched.

## Step 7: Test-fix diagnostic loop — 2026-08-13

### Iteration 1 — 8-round parallel sweep: 90/100 in every round (identical failure set, deterministic not flaky)

Union of failing tests (10, same across all 8 rounds) and dispositions:

| Test | Root cause | Layer fixed |
|---|---|---|
| test_06 7 tests (double_open, reopen edge, re-dispute, reopen-closed, resolve-gate, accept-delivery-gate, escalation edges) | `setup_open_complaint()` lacked a `description` parameter; the kwarg fell into `**order_overrides` and crashed `setup_in_production_order` with TypeError. PRD §3.8 declares `description` as complaint body field — fixture failed to forward it. | test_helpers/fixtures.py |
| test_02 TestSlaWeekendRollover::test_express_friday_confirm_rolls_over_weekend | Test quoted at the default clock 2026-08-01 then confirmed at 2026-08-07T16:00 — the 72h quote expiry (PRD §3.2) had legitimately lapsed, so ERR_QUOTE_EXPIRED was correct server behavior. Moved `set_clock` ahead of `quote_order` so the confirm instant precedes expiry; asserted due_at (2026-08-17T16:00:00Z weekend rollover) unchanged. | test_suite/test_02 |
| test_03 TestQcReworkCycle::test_third_fail_is_terminal_and_rework_rejected | Fixture `setup_track_in_qc_queue` leaves the track QC_QUEUED; the test's first `_drive_fail` re-ran submit+enqueue (AUTHORING→INTERNAL_REVIEW) on a QC_QUEUED track — correctly rejected per PRD §3.3. FAIL #1 now finalizes QC directly, matching the sibling two-cycle test's pattern. | test_suite/test_03 |
| test_05 TestCapacityConservation::test_released_capacity_is_immediately_reusable | `_setup` ends with clock at 14:00; the test then offered a 09:50-start event. Per PRD §3.7 `offer_expires_at = min(offered_at+4h, event.start_at)` — the offer was born expired, so accept correctly raised ERR_OFFER_EXPIRED. Added a clock rewind to 08:00 before creating E4 (PRD's clock capability has no monotonicity constraint); the overlap-with-freed-E1-window assertion is preserved. | test_suite/test_05 |

No implementation changes were needed — every failure was a test-layer bug; the PRD-required server checks (quote expiry, state-machine admissibility, offer expiry) were behaving correctly. No tests deleted; no assertions weakened.

### Iteration 2 — 8-round parallel sweep after the four test-layer fixes: 100/100 in all 8 rounds (800/800 total). CLEAN — loop exits.

No implementation changes were required at any point; all ten failures were test-layer bugs (one fixture forwarding bug with 7-test reach, three test-timeline bugs where the scenario as written violated a PRD rule the server correctly enforced).
