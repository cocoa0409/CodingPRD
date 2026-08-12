# Worklog — task_1248_irb_human_subjects_protocol_review

## Step 1: Create Task Directory — 2026-08-12T07:42:00.000Z

Pre-assigned output folder `tasks/task_1248_irb_human_subjects_protocol_review` with `workspace/` subdirectory already exists. Step 1 treated as done per pipeline instruction (auto-index scan skipped).

## Step 2: Generate Scaffold — 2026-08-12T08:47:00.000Z

First spawn returned a truncated summary with zero files on disk (design reasoning only); re-spawned with a bounded "write files first" instruction. Retry completed. All three scaffold artifacts are on disk and verified for task_1248 (IRB Human Subjects Protocol Review).

**Files written** (all parse with `yaml.safe_load`):
- `/home/ubuntu/github/CodingPRD/tasks/task_1248_irb_human_subjects_protocol_review/SCAFFOLD.yaml` — 98,810 bytes
- `/home/ubuntu/github/CodingPRD/tasks/task_1248_irb_human_subjects_protocol_review/SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 89,567 bytes
- `/home/ubuntu/github/CodingPRD/tasks/task_1248_irb_human_subjects_protocol_review/SCAFFOLD_CORNER_DESIGN.yaml` — 174,922 bytes

**Surface counts**: 13 entities, 11 state machines (Protocol is cyclic with revision + suspension + expiry loops; BoardMeeting has a FAILED_QUORUM→SCHEDULED cycle; ContinuingReview has LAPSED→APPROVED recovery), 7 calculations, 20 ordered validations, 68 endpoints (38 writes incl. `POST /_clock/set_current_utc` with pinned default `2026-05-01T00:00:00Z`, 30 reads covering every FK reverse-reachability), 48 error codes, 6 roles (segregation-of-duties model: PI/Reviewer/IrbChair entity-backed; coordinator/admin/compliance-officer opaque), 2 OCC concurrency rules (modification-create vs agenda-add).

**Difficulty design**: 18 instances, 2 per rule × 9 rules, all names unique, all `${var}` placeholders bound, all grounds resolve. Harder-than-expert levers: dual-variant fee vs compliance-score calcs (provisional 47 vs final 60 divergence gating submission); pinned per-line rounding (449998 vs sum-then-round 449997, literals verified with Decimal); quorum formula with prisoner-representative conditional branch; depth-3 cascades from two different triggers (finding→suspension→agenda-removal→meeting-cancel; clock-sweep→CR-lapse→EXPIRED→auto-case→score); state×safety and safety×constraint priority-conflict pairs; half-open room vs closed reliance-window overlap semantics; consent-cardinality and member-workload compensating invariants.

**Corner design**: 61 instances (50 full test_recipes + 11 `excluded_because` stubs citing difficulty instances), spanning all 9 claim-extraction sections; every error code in the catalog is covered by at least one full instance or stub.

**Lint verdict (verbatim)**: `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (68 endpoints, 13 entities, 18 §1.8 + 50 §1.9 instances, 907 calls scanned.) Fixes applied en route: three YAML flow-context syntax errors (unquoted `?` input markers, `$.data[0].id` captures, bracketed grounds refs) and one entity-level grounds ref tightened to a specific transition. No sibling task directories were consulted.

## Step 3: Copy Shared Files — 2026-08-12T08:48:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_1248_irb_human_subjects_protocol_review/workspace/INSTRUCTION.md` (1,424 bytes).

## Step 4: Generate PRD — 2026-08-12T09:05:00.000Z

PRD generation complete. `/home/ubuntu/github/CodingPRD/tasks/task_1248_irb_human_subjects_protocol_review/workspace/PRD.md` written — 56,198 bytes, 363 lines.

**Section inventory:**
- §1 Introduction (2 paragraphs, business-context angle)
- §2 Global Specifications: 2.1 RBAC (6 roles with per-role `identity` prose, headers, 401/403), 2.2 API Response Structure (verbatim fixed block, byte-identical including `req_RANDOMALPHANUM123456`, `2025-05-24T10:30:00.123Z`, `UNIQUE_ERROR_IDENTIFIER_STRING`, `"data": { }`), 2.3 Pagination (limit 10/1/100, offset 0, `created_at` ascending default with the agenda-listing exception flagged), 2.4 Logical Clock & Sweeps (startup default `2026-05-01T00:00:00Z`, three sweep families, `to_iso8601` and the four response counters), 2.5 Common Resource Properties (all 13 entities carry id/created_at/updated_at/version; derived-field recompute = mutation), 2.6 Nested Resource Retrieval (left-to-right, all 13 404 variants), 2.7 Fee Precision (integer cents, per-line round-half-up then sum, industry multiplier 1.5, all fee bases), 2.8 OCC (both rules: `expected_protocol_version` → `ERR_STALE_PROTOCOL_VERSION` 412; `expected_meeting_version` → `ERR_STALE_MEETING_VERSION` 412; no time-overlap framing), 2.9 Validation Pipeline precedence (10-tier global order matching scaffold priorities 1–20), 2.10 Cascade Invariants (suspension cascade, asymmetric reinstatement, consent cardinality, quorum/vote snapshots)
- §3 Business Logic: 9 subsections (registry onboarding; intake/submit gates/determination; consent & waivers; assignments & conflicts; expedited determination; board meetings/quorum/voting; modifications & continuing review; adverse events/non-compliance/suspension/reinstatement; reliance agreements)
- §4 Endpoint table: 68 rows, 4 columns, all paths verified against scaffold (58 unique paths)
- §5 Error catalogue: 48 rows, 2 columns

**Coverage audit (vs scaffold totals):**
- Contract 1 field coverage: 89 required names (79 entity fields + endpoint inputs/query params + common fields) — 89 present in backticks, 0 missing
- Contract 2 rule coverage: all 20 priority-ordered validations expressed with their fixed orderings (submit gate order debarred→training→score; convene order eligibility→count→composition; expedited APPROVE chain); both OCC rules with write endpoint, OCC field, error id, and 412 status; all 65 state-machine transitions across 11 machines with from/to states, preconditions→error ids, and side effects (incl. suspension 3-link cascade, asymmetric reinstatement, LAPSED_CR case persistence); all 7 calculations in precise prose (review_fee round-then-sum, compliance score 100−20/−5/−8 with debarment below 60, quorum floor-half-plus-one, strict-majority vote with tie-fails, CR 365/180-day intervals with 60-day inclusive window and strict lapse, AE 5/5/15-day deadlines with on-time-at-deadline, reviewer auto-select with 5-assignment cap and created_at tie-break); all endpoint side effects and applies_to scopes enumerated; sibling branches (4 vote outcomes, 3 respond values, both finding values) rendered with equal density — 0 gaps found
- Contract 3 §3 path purity: 561 backticked tokens scanned in §3, 0 path/method violations
- All 48 error ids, all enum/state values (incl. `REFER_TO_FULL_BOARD`, `ACCEPT`/`DECLINE`/`RECUSE`, `CONFIRMED`/`NOT_CONFIRMED`), and all 6 role names appear in backticks; zero operator-syntax leaks (==/>=/floor()/etc.) and zero fuzzy hedging words outside the fixed §2.2 block

**Notable rendering decisions:** reliance-window "closed interval, touching endpoints intersect" and meeting-room "half-open occupation" rendered as prose; reliance-create terminal-protocol rejection mapped to `ERR_INVALID_STATE` (the only catalog fit); compliance-score deduction interplay at AE triage expressed as the −5 open-case deduction replacing the −8 late-unfiled one; one late Edit added the missing `source` field name (caught by the mechanical Contract 1 pass).

## Step 5: Generate Unit Tests — 2026-08-12T09:37:00.000Z

Generation complete for task_1248 (IRB Human Subjects Protocol Review).

**Files written (all under /home/ubuntu/github/CodingPRD/tasks/task_1248_irb_human_subjects_protocol_review/):**
- test_helpers/ (9 files): `__init__.py`, `types.py` (13 entity TypedDicts, all status/role enums), `api_client.py` (all 61 PRD §4 endpoints + clock), `api_errors.py` (all 48 error IDs with HTTP map registered via `set_error_http_status_map`), `assertions.py` (per-entity assertions + timestamp-instant comparator), `factories.py` (input-only payload factories with unique-email sequencing), `constants.py` (fee schedule, score deductions, intervals, windows), `test_users.py` (opaque-role constants + `make_pi/reviewer/chair_headers` entity-backed builders), `fixtures.py` (composite lifecycle builders: expedited-approval scenario, AWAITING_FULL_BOARD scenario, quorum roster, suspension via confirmed finding, reliance helpers).
- test_suite/ (11 files): `conftest.py` + `test_01`…`test_10` grouped by concern (registry/listings/RBAC, submission gates, fees/determination, expedited review/assignments, board meetings, voting, modifications/consent, continuing review, compliance/suspension/reinstatement, adverse events/reliance).

**Test counts:** 84 tests total, all collecting cleanly via `python3 -m pytest --collect-only` (0 errors).
- Queue A (Difficulty): 36 tests — every one of the 18 §1.8 instances has exactly ≥2 tests tagged `Design: Difficulty/<rule_id>/<instance.name>`.
- Queue B (Corner): 48 tests — every covered non-stub §1.9 instance has exactly 1 test tagged `Design: Corner/<section>/<instance.name>`. All 11 `excluded_because:` stubs (8 errors-section + 3 cross-cutting) were not translated; all 11 stub cross-references resolve to real difficulty instances.
- Tag audit: every test carries exactly one Design tag as the last docstring line; no unknown tags; no difficulty shortfalls; no `skip`/`xfail` markers; no scaffold references in generated code; every docstring citation contains a contiguous verbatim quote that greps against PRD.md.

**Instances skipped (2, both queue B, both for the same unique-derivability failure):**
1. `Corner/entities/protocol_create_applies_defaults_and_system_fields` — its assert bundle requires the literal `version == 1` at creation; PRD §2.5 says only that version is "a system-managed counter that increments on every mutation" and never pins the initial value, so a faithful PRD-only reader could legitimately start at 0 or 1.
2. `Corner/consistency_model/immediate_consistency_read_after_write` — same root cause: its asserted outcome includes "Create response carried version == 1", not uniquely derivable from the PRD.

Per the design-index-only contract, these gaps were left as gaps (no weakened assertion, no placeholder, no skip marker).

## Step 6: Generate Implementation — 2026-08-12T09:37:00.000Z

The implementation is complete and verified. Final summary:

## Files written

All under `/home/ubuntu/github/CodingPRD/tasks/task_1248_irb_human_subjects_protocol_review/workspace/implementation/`:

| File | Bytes | Purpose |
|---|---|---|
| `start.sh` | 396 | Executable launcher; guarded `pip install` (skipped when flask importable), `exec python3 app.py` in foreground, binds `0.0.0.0:$PORT` (default 10000) |
| `requirements.txt` | 16 | `flask>=3.0,<4.0` |
| `app.py` | 67,523 | Flask entry point, all 68 routes, error handlers |
| `core.py` | 10,153 | Response envelope (`meta`/`response_type`/`data`, `error_id`/`message`), logical clock (starts exactly `2026-05-01T00:00:00Z`), ISO8601 3-fractional-digit timestamps, pagination (`limit`/`offset`/`total_count`/`has_more`, default 10, min 1, max 100), auth (`X-User-ID`/`X-User-Role`, 6 roles), validation helpers, OCC record factory (`id`/`created_at`/`updated_at`/`version`) |
| `db.py` | 697 | 13 in-memory dict tables, empty at boot, no seeding |
| `errors.py` | 2,824 | `ApiError` + all 48 error-ID constants |
| `services.py` | 10,764 | Calculations, cascades, clock sweep |

## Endpoint count
68/68 — exact match with SCAFFOLD.yaml's declared method+path pairs (verified programmatically; the one apparent diff was a regex artifact from a route decorator split across two lines).

## State machines implemented (12)
Protocol (14 states incl. cyclic suspension/reinstatement, pre_suspension_state restore), ConsentDocument (supersede invariant), ReviewAssignment (OFFERED/ACCEPTED/DECLINED/RECUSED/EXPIRED/SUBMITTED with `active_assignment_count` maintenance), ConflictDeclaration (CONFLICTED adjudication cascade: recuse open assignments + void submitted recommendations), BoardMeeting (convene quorum snapshot, adjourn→DEFERRED, FAILED_QUORUM→reschedule, auto-CANCELLED on item_count→0 via removal), AgendaItem (vote outcomes, deferral), ModificationRequest (MINOR chair / MAJOR board routing, consent supersede side effect), ContinuingReview (windowed submit, APPROVED-from-LAPSED reinstatement of EXPIRED protocol, cycle++ creation), AdverseEventReport (triage→LATE_AE case, disposition→suspension cascade + AE_ACTION case), NonComplianceCase (finding→suspension + debarment scoring), RelianceAgreement (execute gating, suspension/reinstatement riding protocol state).

## Calculations implemented (7)
`review_fee` (Decimal, per-line round-half-up then sum; industry multiplier 1.5; provisional at first submit, settled base at determination, +112,499-type site line per execute), `compliance_score` (provisional = 100 −20·confirmed −5·open −8·late-unfiled; final = 100 −20·confirmed; DEBARRED < 60), `quorum_determination` (floor(active/2)+1, category composition incl. prisoner-rep branch), `vote_outcome` (recusal-adjusted eligible count, tally equality, strict `2·for > eligible`), `continuing_review_schedule` (180/365-day intervals, 60-day window, inclusive bounds, strict-`>` lapse), `ae_timeliness` (5/15-day windows, inclusive deadline), `reviewer_selection` (pool filters, count-ASC then created_at-ASC tie-break). Clock sweep covers all three families (CR lapse cascade, meeting grace failure, assignment expiry) and reports the three counters.

## Boot verification
- `start.sh` exists, executable (`-rwxrwxr-x`), guarded install, `exec` foreground
- `python3 -c "import app"` — clean
- Fresh boot on allocated port answered `POST /_clock/set_current_utc` with HTTP 200 and correct envelope
- Deep smoke tests passed: fee math (provisional/settled/delta, industry multiplier, reliance surcharge), expedited approval with CR cycle creation, lapse sweep (EXPIRED + LAPSED_CR case + score recompute), suspension/reinstatement asymmetry, OCC 412s, quorum/composition ordering, vote tally/eligible-count freezing, conflict recusal/voiding cascade, waiver-criteria gate, debarment at final < 60, window boundary inclusivity — all error IDs and HTTP statuses match the scaffold catalog

**Orchestrator note:** pre-sweep route parity verified independently — all 68 SCAFFOLD.yaml (method, path) pairs match the Flask routes registered in `workspace/implementation/app.py` exactly (parameter names normalized).

## Step 7: Run Tests and Iterate — 2026-08-12T09:51:00.000Z

**Iterations run: 2** (iteration 1: 11 deterministic failures, identical across all 8 rounds — zero flakiness; iteration 2: all 8 rounds × 84/84 passed).

**Tests deleted: 0** — every failing test traced to a verbatim PRD rule; none exhibited a silence or unique-derivability collapse.

**Fixes applied to test_suite/ (4 files, 4 tests):**
- `test_01_registry_protocols_and_listings.py::test_clock_set_echoes_time_and_reports_zero_sweeps` — exact-string assertion `data["current_utc"] == "2026-05-10T00:00:00Z"` over-specified the rendering; PRD §2.4 pins only that the response "reports the new clock reading as `current_utc`" (the instant). Split per partial-coverage: kept the covered instant assertion via `assert_timestamp_equals`, dropped the underivable string-format assertion.
- `test_04_expedited_review_and_assignments.py::test_duplicate_assignment_rejected` and `::test_reviewer_auto_selection_ranking_and_tiebreak` — `validate_success(resp)` defaulted to 200 on a create endpoint; PRD §4 verbatim: "Operations that create a new resource return `201 Created`". Added `expected_status=201`.
- `test_05_board_meetings.py::test_meeting_room_adjacent_start_allowed` — same 200-vs-201 mis-translation on `create_board_meeting`; added `expected_status=201`.

**Fixes applied to test_helpers/ (1 file):**
- `fixtures.py::setup_awaiting_full_board_scenario` — added optional `chair=` parameter so a test with a pre-registered quorum roster reuses its chair instead of registering a sixth ACTIVE member (which inflated the §3.6 quorum threshold floor(6/2)+1=4 and broke the tests' designed 5-member/threshold-3 rosters). Callers updated: `test_05` (both prisoner-branch tests, `test_adjourn_defers_listed_items`) and `test_06::_convened_initial_review_item` (fixes `test_vote_succeeds_after_convene`, `test_vote_tally_must_match_recusal_adjusted_denominator`, `test_disapproved_terminal_lockdown`). This was the ≥5-tests-same-setup-error triage pattern — helper was the first suspect and was the culprit.

**Fixes applied to implementation/ (1 file, 2 functions):**
- `app.py::offer_assignment` — reordered the explicit-reviewer branch so the conflict gate (`ERR_REVIEWER_CONFLICTED`) fires before the uniqueness constraint (`ERR_DUPLICATE_ASSIGNMENT`), matching PRD §2.9's fixed precedence (level 5 business safety gates before level 6 business constraints). Fixed `test_conflict_safety_beats_duplicate_constraint`.
- `app.py::add_agenda_item` — removed the standalone `touch(meeting)` so each successful addition increments the meeting `version` exactly once (the `item_count` recompute is that mutation per §2.5), per PRD §3.6 "Each successful addition increments the meeting's `version` and recomputes its `item_count`". The double increment broke the OCC version arithmetic in `test_agenda_capacity_ninth_item_rejected`.

**Orchestrator verification:** all 8 `results.{1..8}.json` files on disk, every round `passed: 84, failed: 0, total: 84`.

## Step 8: Finalize PRD — 2026-08-12T09:56:00.000Z

Done. PRD_FINALIZED.md is written at `/home/ubuntu/github/CodingPRD/tasks/task_1248_irb_human_subjects_protocol_review/workspace/PRD_FINALIZED.md` with exactly two inline revisions, both traced to Step 7 diff items.

## Line counts
- PRD.md: 363 lines; PRD_FINALIZED.md: 363 lines — 0% line-count delta (2 sentences revised in place, none added/removed).

## Changes (one bullet per edit)
- **§2.4** — revise — the clock-set response sentence now pins `current_utc` rendering: "rendered as an ISO 8601 UTC timestamp with three fractional digits, the same rendering discipline as the resource timestamps of §2.5" — `implementation/app.py:60` (`fmt_iso(now())`) + `implementation/core.py:65-70` (`fmt_iso` always emits `%Y-%m-%dT%H:%M:%S.` + 3 digits + `Z`). Traces to Step 7's `test_clock_set_echoes_time_and_reports_zero_sweeps` fix, which found PRD silent on the string rendering.
- **§3.6** — revise — the agenda-addition sentence now reads "increments the meeting's `version` exactly once and recomputes its `item_count` — the recomputation is that single mutation per §2.5, not an additional increment on top of the addition" — `implementation/app.py:958-960` (`recompute_meeting_item_count` is the only touch) + `implementation/services.py:128-135`. Traces to Step 7's `add_agenda_item` fix (removed the standalone `touch` that double-bumped `version` and broke `test_agenda_capacity_ninth_item_rejected`'s OCC arithmetic).

## Step 7 items deliberately not patched
- `test_duplicate_assignment_rejected`, `test_reviewer_auto_selection_ranking_and_tiebreak`, `test_meeting_room_adjacent_start_allowed` — pure test bugs (`validate_success` defaulted to 200 on create endpoints); PRD §4 already verbatim pins "Operations that create a new resource return `201 Created`", and all 12 create routes return 201 (`app.py:148,195,271,513,654,756,857,961,1233,1437,1522,1632`). PRD already determines → kept verbatim.
- `fixtures.py::setup_awaiting_full_board_scenario` `chair=` param — pure helper bug (inflated ACTIVE roster shifted the quorum floor); PRD §3.6 already pins threshold = floor(ACTIVE/2)+1 and impl matches (`app.py:1029-1031`). No edit.
- `offer_assignment` conflict-before-duplicate reorder — impl was fixed *to match* PRD §2.9, which already lists `ERR_REVIEWER_CONFLICTED` at precedence level 5 ahead of `ERR_DUPLICATE_ASSIGNMENT` at level 6; §3.4 also pins conflicted-reviewer offers → `ERR_REVIEWER_CONFLICTED`. PRD already determines → kept verbatim.

## Per-edit pre-edit search log
1. **§2.4 clock rendering edit**
   - (a) Subject: string rendering of `current_utc` in the clock-set response.
   - (b) Enumerated/read: `app.py:51-64` (`clock_set`, sole producer of `current_utc` — grep confirms no other emitter); `core.py:65-70` (`fmt_iso`, the same renderer behind `created_at`/`updated_at`, which §2.5 already describes as three-fractional-digit ISO 8601 UTC — so the edit harmonizes rather than conflicts); `services.py:258-307` (`run_sweep` touches only counters, not the response shape).
   - (c) Wording adjustment: anchored to §2.5's existing phrase instead of inventing a new format spec, so every other timestamp path (all use `fmt_iso`) stays consistently described.
2. **§3.6 agenda-addition version edit**
   - (a) Subject: number of meeting `version` increments per successful agenda-item addition.
   - (b) Enumerated/read every meeting-`version` path: `create_board_meeting` (`app.py:833-857`, `new_record` → v1), `add_agenda_item` (`app.py:881-961`, single touch via recompute), `convene_meeting` (`app.py:1007-1051`, one touch), `adjourn_meeting` (`app.py:1054-1068`, status touch + recompute touch — legitimately two, but not an addition), `reschedule_meeting` (`app.py:1071-1095`, one touch), `vote_agenda_item` (`app.py:1098+`, touches item/protocol, not the meeting), `run_sweep` FAILED_QUORUM touch (`services.py:286-294`), `suspend_protocol` recompute + cancel touches (`services.py:142-168`).
   - (c) Wording adjustment: scoped strictly to "successful addition" ("exactly once … not an additional increment on top of the addition") with no universal claim about meeting mutations, so the adjourn and suspension-cascade paths (which touch the meeting differently) are not mis-described.

## Step 9: Complete PRD — 2026-08-12T10:12:00.000Z

All edits are complete. PRD_COMPLETED.md is written. Here is the summary.

## Summary

**Source vs output:** `PRD_FINALIZED.md` → `PRD_COMPLETED.md` (both at `/home/ubuntu/github/CodingPRD/tasks/task_1248_irb_human_subjects_protocol_review/workspace/`). Line counts: 363 → 363 (all changes are inline in existing paragraphs; no sections added). Char count: 56,461 → 61,545 (**+5,084 chars**).

**Counts:** 28 ambiguity-pins, 8 mismatch-revisions (36 distinct change points total).

### Mismatch-revisions (PRD described behavior impl does not exhibit)
- §2.8 — revise — mismatch — both OCC fields (`expected_protocol_version`, `expected_meeting_version`) are optional, not mandatory; check runs only when supplied; non-integer value → `ERR_VALIDATION` 400 — `app.py:889,929-935,1205,1217-1223`
- §2.10 — revise — mismatch — suspension removes `LISTED` agenda items only on `SCHEDULED` meetings (not merely "not yet convened"; `CONVENED`/`FAILED_QUORUM` items untouched) — `services.py:153-161`
- §3.2 — revise — mismatch — submission gate order: state legality (`ERR_INVALID_STATE` from non-submittable states) runs *before* ownership, then `pi_id` resolution (`ERR_INVESTIGATOR_NOT_FOUND`), then the debarred/training/score chain, then consent completeness — `app.py:326-330`, `app.py:297-318`
- §3.2 — revise — mismatch — the return lever's `reason` is accepted but not persisted on the protocol — `app.py:352-354`
- §3.6 — revise — mismatch — meeting scheduling evaluates the future-start check before the room-overlap check (overrides the §2.9 tier order) — `app.py:841-846`
- §3.6 — revise — mismatch — agenda-listing business shapes also admit `SUSPENDED`/`EXPIRED` protocols: initial-review form allows `AWAITING_FULL_BOARD|SUSPENDED|EXPIRED`; modification form allows `APPROVED|SUSPENDED|EXPIRED` — `app.py:898-909`
- §3.7 — revise — mismatch — modification filing: `expected_protocol_version` described as optional; body (`scope`, `description`) parsed before ownership/state gates — `app.py:1201-1215`
- §3.8 — revise — mismatch — case `closure_note` is accepted but not persisted — `app.py:1592-1593`

### Ambiguity-pins (PRD silent; pinned to impl)
- §2.1 — insert — `IrbChair` with unresolvable member id → `ERR_FORBIDDEN`; member `status` not examined (INACTIVE chair may act) — `core.py:186-194`
- §2.2 — insert — `api_request_timestamp` rendered from the wall clock, not the logical clock — `core.py:77-84`
- §2.3 — revise — `limit`/`offset` out-of-range values clamped (to [1,100] / ≥0), non-integer → `ERR_VALIDATION` 400; `has_more` = `offset` + returned < `total_count` — `core.py:95-145`
- §2.3 — revise — default sort ties broken by `id` ascending — `core.py:148-157`
- §2.4 — insert — clock may be set to any instant; no forward-only constraint — `app.py:51-57`, `core.py:35-37`
- §2.5 — insert — resource timestamps rendered from the logical clock — `core.py:320-334`
- §2.5 — insert — `version` starts at 1 on creation — `core.py:320-327`
- §2.9 — insert — request fields validated at point of first use; body-parse-ahead endpoints (modification filing, determination) surface `ERR_VALIDATION` ahead of higher-tier gates — `app.py:1201-1207`, `app.py:366-368`
- §3.1 — insert — duplicate investigator email → `ERR_VALIDATION` 400 — `app.py:136-137`
- §3.1 — insert — duplicate member email → `ERR_VALIDATION` — `app.py:184-185`
- §3.1 — insert — deactivate/reactivate are unconditional flips, no state precondition — `app.py:219-236`
- §3.3 — insert — consent uploads accepted in any protocol state — `app.py:481-487`
- §3.4 — insert — explicit-reviewer offer gates in order: member exists (`ERR_MEMBER_NOT_FOUND`), `ACTIVE` (else `ERR_NO_ELIGIBLE_REVIEWER`), conflict (`ERR_REVIEWER_CONFLICTED`), then uniqueness; five-assignment ceiling constrains only auto-selection; offering imposes no protocol-state gate — `app.py:589-638`
- §3.4 — insert — declaration adjudication requires `PENDING_REVIEW`, else `ERR_INVALID_STATE` — `app.py:788-789`
- §3.5 — revise — chair-conflict check applies to all three expedited outcomes, before outcome-specific gates — `app.py:397-399`
- §3.6 — insert — agenda deliberation-order ties (after protocol `created_at`) broken by agenda item `id` — `app.py:971-977`
- §3.6 — insert — vote: tally-integrity check fires before consent-side gates; consent gates (`ERR_NO_APPROVED_CONSENT`, referenced-doc existence `ERR_CONSENT_DOC_NOT_FOUND` / `SUBMITTED` / waiver) run only when the recorded outcome is `APPROVE` — `app.py:1124-1152`
- §3.7 — insert — `new_consent_document_id` not validated at filing time, examined only at approval — `app.py:1204,1224-1231`
- §3.7 — revise — modification adjudication requires chair non-conflicted (`ERR_CHAIR_CONFLICTED`) on both `APPROVE` and `DENY`, before the `MAJOR` routing gate — `app.py:1268-1273`
- §3.7 — revise — referenced doc must exist (`ERR_CONSENT_DOC_NOT_FOUND`) and be `SUBMITTED`; every modification approval (chair or board) increments the protocol's `version` with or without a replacement doc — `app.py:1275-1289`, `app.py:1168-1176`
- §3.7 — insert — continuing-review list supports an optional `status` filter — `app.py:1307-1317`
- §3.7 — revise — CR submission: cycle state gate runs before the ownership check — `app.py:1325-1332`
- §3.7 — insert — CR adjudication chair-conflict check evaluated before the cycle's state gates — `app.py:1359-1361`
- §3.7 — revise — lapse cascade: `APPROVED`→`EXPIRED` transition only when protocol is `APPROVED`; `LAPSED_CR` case opening and score recompute occur regardless of protocol state — `services.py:275-284`
- §3.7 — revise — approving a `LAPSED` cycle is legal only while the protocol is `EXPIRED`, else `ERR_INVALID_STATE` — `app.py:1371-1374`
- §3.7 — revise — closing a protocol moots open cycles (`PENDING_SUBMISSION`/`SUBMITTED`/`CHANGES_REQUESTED`) by moving them to `APPROVED` — `app.py:454-459`
- §3.8 — revise — `SUSPEND_PROTOCOL` disposition opens the `AE_ACTION` case whatever the protocol's state; the suspension cascade fires only from `APPROVED`/`EXEMPT_ACTIVE` — `app.py:1500-1505`
- §3.8 — insert — debarment flip to `DEBARRED` is one-way; score recovery never restores `ACTIVE` — `services.py:104-105`
- §3.9 — insert — reliance creation runs the terminal-state check before the window-validity check — `app.py:1616-1622`

Key finding: the largest genuine PRD-vs-impl divergences were (1) OCC fields being optional rather than mandatory, (2) the submission pipeline checking state before ownership, and (3) agenda listings accepting `SUSPENDED`/`EXPIRED` protocols — which the PRD's own `SUSPENSION_REVIEW` priority class implicitly requires but its state-gate prose forbade. All other behaviors (fee math, score ledger, sweep cascades, quorum math, vote outcomes, envelope shape, endpoint/role table, error catalogue) matched the PRD as written.
