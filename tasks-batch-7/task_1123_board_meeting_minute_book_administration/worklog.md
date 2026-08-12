# Worklog — task_1123_board_meeting_minute_book_administration

## Step 1: Create Task Directory — 2026-08-10T19:53:00.000Z

Pre-assigned output folder `tasks/task_1123_board_meeting_minute_book_administration` with `workspace/` subdirectory already exists; Step 1 auto-index scan skipped per instructions. Treating Step 1 as done.

## Step 2: Generate Scaffold — 2026-08-10T20:43:00.000Z

Scaffold generation complete for task 1123 (Board Meeting & Minute Book Administration). All artifacts written, lint-clean.

**Files written**
- `/home/ubuntu/github/CodingPRD/tasks/task_1123_board_meeting_minute_book_administration/SCAFFOLD.yaml` — 1,731 lines (§1.0–§1.7 only; no `scaffold_difficulty_design`/`scaffold_corner_design` keys)
- `/home/ubuntu/github/CodingPRD/tasks/task_1123_board_meeting_minute_book_administration/SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 1,542 lines (single top key `scaffold_difficulty_design`)
- `/home/ubuntu/github/CodingPRD/tasks/task_1123_board_meeting_minute_book_administration/SCAFFOLD_CORNER_DESIGN.yaml` — 2,110 lines (single top key `scaffold_corner_design`)

**Counts**
- Entities: 16 (Corporation, Bylaws, Director, Committee, CommitteeMembership, Meeting, MeetingNotice, AgendaItem, BoardPackage, PackageDocument, AttendanceRecord, Resolution, VoteRecord, ConflictDisclosure, Minutes, AuditRequest)
- Endpoints: 79 (flat topology, `api_prefix: ""`, plus `POST /_clock/set_current_utc` with the mandatory 2026-05-01T00:00:00Z default)
- Errors: 33; state machines: 13; calculations: 11; validations: 9 priority rows; roles: 4 (CorporateSecretary/ExternalAuditor opaque; Director/BoardChair entity_backed:Director); OCC concurrency rules: 2 (bylaws adoption on Corporation.version, meeting reschedule on Meeting.version)
- Difficulty instances: 20 (9 rules; combinatorial_formula and non_linear_state_machine carry 3 each, rest 2)
- Corner instances: 59 total (49 active test recipes + 10 `excluded_because` stubs) across all 9 taxonomy sections

**Design highlights** — compliance/audit archetype with multi-party-negotiation blend: dual-variant quorum (at-call snapshot vs rolling presence) and vote outcome (present-and-voting vs full-board majority); combinatorial instances in all three modes (notice-day branching, pinned round-per-resolution-then-mean yielding literal 44.5 vs pooled 44.4, snapshot evaluation order for consent required count); cycles on Resolution/Minutes/BoardPackage; depth-3 meeting-cancel and depth-2 director-resignation cascades; half-open (calendar) vs closed-interval (disclosure) overlap semantics; OCC-guarded supersede/reschedule; ops-run checkpoint driving term expiry, consent lapse, and strict-greater retention purge; reconstruction projection with purged-gap failure.

**Verification** — `scaffold_lint.py` verdict, verbatim:
```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```
Additional self-checks passed: instance names unique across both design files, no forbidden race vocabulary, all 33 error codes referenced by at least one instance, enum-value closure clean, all grounds resolve, and manual call-by-call rule replay fixed three latent fixture bugs (agenda-item creation after convene, unreachable ERR_NO_ACTIVE_DIRECTORS setup, missing schema-validation row) before finalizing.

## Step 3: Copy Shared Files — 2026-08-10T20:44:30.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` to `tasks/task_1123_board_meeting_minute_book_administration/workspace/INSTRUCTION.md` (1,424 bytes).

## Step 4: Generate PRD — 2026-08-10T21:03:00.000Z

All verifications pass (the trailing `NameError` is a harmless heredoc-delimiter artifact after all output was produced). The PRD is complete and verified.

## Summary

**File written:** `/home/ubuntu/github/CodingPRD/tasks/task_1123_board_meeting_minute_book_administration/workspace/PRD.md`

**Size:** 360 lines, 8,291 words, 25 numbered sections (§1 Introduction; §2.1–§2.11 Global Specifications; §3.1–§3.9 Business Logic; §4 Endpoint Definitions; §5 Error Code Catalogue). §2.2 emitted byte-for-byte verbatim from `section-2.2-response-structure.md` (verified programmatically).

**Entity coverage:** 16/16 scaffold entities (Corporation, Bylaws, Director, Committee, CommitteeMembership, Meeting, MeetingNotice, AgendaItem, BoardPackage, PackageDocument, AttendanceRecord, Resolution, VoteRecord, ConflictDisclosure, Minutes, AuditRequest) — all 98 entity fields appear verbatim in backticks, along with all 53 request-body inputs, 23 query params, and the `id` path param.

**Endpoint coverage:** 79/79 scaffold endpoints in the §4 table (4 columns only: Method, Path, Description, Authorized Role(s)); 33/33 error IDs in the §5 table (2 columns only). All 40 state names, 70 enum values, and 33 error IDs appear in the prose.

**Hard contract verdicts:**

```
Field coverage check (Contract 1):
- entities[].fields: 98 required, 98 present, 0 missing
- endpoints[].request_body: 53 required, 53 present, 0 missing
- endpoints[].query_params: 23 required, 23 present, 0 missing
- endpoints[].path_params: 1 required, 1 present, 0 missing
Status: PASS

Rule coverage check (Contract 2):
- validations[] with priority: 9 checked, 9 expressed in §2.11 as an ordered nine-tier narrative, 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (adoption → expected_corporation_version + ERR_STALE_VERSION/412; reschedule → expected_meeting_version + ERR_STALE_MEETING_VERSION/412; no race framing), 0 missing
- state_machines[].transitions: 43 checked, 43 fully expressed (from/to states, preconditions with error IDs, side-effect cascades), 0 missing
- calculations[]: 11 checked, 11 fully expressed in precise prose (incl. ceiling-before-max quorum, doubling rule for ORDINARY, floor-plus-one for SPECIAL, pinned consent-snapshot order, per-resolution round-half-up-before-averaging, half-open vs closed interval semantics, 86,400-second days, 365-day years, pipe-delimited digest lines), 0 missing
- validations[] conditions: 9 checked, 9 matchable to error_ids in §2.11/§3 prose, 0 missing
- endpoints[].side_effects / applies_to: all expressed (resign/term-expiry, dissolve, cancel, re-table/redraft voiding, purge, checkpoint rosters; temporal/compliance tier scopes enumerated), 0 missing
- entities[].fields[] structured content: defaults and initial values reconstructible (e.g., PENDING_REVIEW independence, zeroed tallies/seal_count, empty minutes content, version 1 at creation), 0 missing
- sibling-branch symmetry: all parallel branches rendered with equal density (ORDINARY/SPECIAL, unanimous/majority, snapshot/rolling, ADOPTED/REJECTED, COMPLETED/FAILED, REGULAR-ANNUAL/SPECIAL notice), 0 asymmetric
Status: PASS

Path purity check (§3 only) (Contract 3):
- backtick tokens scanned: 597
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Additional lint: no fuzzy/approximating words ("approximately", "roughly", "conservatively"), no pseudocode operator symbols (`==`, `>=`, `+=`, etc.) in prose, varied paragraph starters (no "The system…" repetition), and the withheld test-targeting files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were never opened or referenced.

## Step 5: Generate Unit Tests — 2026-08-10T21:29:00.000Z

All checks pass. Here's the final summary.

---

## Summary

### Files written

**test_helpers/** (9 files, 1822 lines):
- `/home/ubuntu/github/CodingPRD/tasks/task_1123_board_meeting_minute_book_administration/test_helpers/__init__.py` — 133 lines (barrel export)
- `/home/ubuntu/github/CodingPRD/tasks/task_1123_board_meeting_minute_book_administration/test_helpers/types.py` — 420 lines (TypedDicts + 23 enums)
- `/home/ubuntu/github/CodingPRD/tasks/task_1123_board_meeting_minute_book_administration/test_helpers/api_client.py` — 265 lines (`ApiClient(GenericApiClient)` with one method per endpoint)
- `/home/ubuntu/github/CodingPRD/tasks/task_1123_board_meeting_minute_book_administration/test_helpers/api_errors.py` — 81 lines (33 error IDs + status map, registered with framework)
- `/home/ubuntu/github/CodingPRD/tasks/task_1123_board_meeting_minute_book_administration/test_helpers/assertions.py` — 211 lines (per-entity assertions)
- `/home/ubuntu/github/CodingPRD/tasks/task_1123_board_meeting_minute_book_administration/test_helpers/factories.py` — 170 lines
- `/home/ubuntu/github/CodingPRD/tasks/task_1123_board_meeting_minute_book_administration/test_helpers/constants.py` — 15 lines
- `/home/ubuntu/github/CodingPRD/tasks/task_1123_board_meeting_minute_book_administration/test_helpers/test_users.py` — 32 lines (TEST_USERS + `make_director_headers` / `make_chair_headers` for entity-backed roles)
- `/home/ubuntu/github/CodingPRD/tasks/task_1123_board_meeting_minute_book_administration/test_helpers/fixtures.py` — 495 lines (composite fixtures across all 5 tiers)

**test_suite/** (18 files, 3265 lines):
- `conftest.py` — 30 lines
- 17 test files, `test_01_creation_and_validation.py` through `test_17_cross_entity_state.py`

### Test counts

- **Total tests**: 106
- **Queue A (Difficulty) tests**: 40 (20 instances × exactly 2 tests each — all 20 instances covered at ≥2)
- **Queue B (Corner) tests**: 66 (covering all 49 non-stub instances at ≥1)
- **Skipped instances**: 0 — every non-stub instance in both indices passed the PRD-first two-condition filter; the 10 `excluded_because:` stubs in queue B were correctly NOT translated (their difficulty-design cross-references all resolve).

### Lint / stage-check verdicts

- **Coverage audit (queue A)**: PASS — 20/20 instances have ≥2 tagged tests.
- **Coverage audit (queue B)**: PASS — 49/49 non-stub instances have ≥1 tagged test; 10/10 stubs have no test.
- **Docstring C4 (one Design: tag per test, resolves to a real instance)**: PASS — 106 tests, exactly one Design line each; 0 extra tags not present in either yaml.
- **PRD citation C1 verbatim grep**: PASS — all 117 quoted PRD citations contain a ≥8-word substring that survives literal grep of `workspace/PRD.md` (whitespace-normalized).
- **No `pytest.mark.skip` / `skipif` / `xfail` markers**: PASS — 0 found.
- **No scaffold self-references ("scaffold", "Table N", "§1.x")** in generated code: PASS — 0 hits.
- **Python compile**: PASS — all 18 test files + 9 helper files compile clean.
- **Import**: PASS — all test modules import cleanly against the framework.

## Step 6: Generate Implementation — 2026-08-10T21:39:00.000Z

Implementation complete and verified. Final summary:

## Files written (all under `.../workspace/implementation/`)

| File | Lines | Purpose |
|---|---|---|
| `start.sh` | 10 | Foreground launcher; guarded `pip install` (no-op once Flask present), `exec python3 app.py`, `0.0.0.0:$PORT` (default 10000) |
| `requirements.txt` | 1 | `Flask>=3.0,<4.0` |
| `app.py` | 609 | Flask wiring: auth `before_request`, ApiError/404/405/500 handlers, all 79 routes |
| `db.py` | 72 | Empty-at-boot in-memory stores, logical clock (default `2026-05-01T00:00:00Z`), `touch()` (updated_at + version bump) |
| `errors.py` | 52 | `ApiError` + all 33 catalog error IDs with their exact HTTP statuses |
| `middleware.py` | 48 | `X-User-ID`/`X-User-Role` extraction, role-membership checks |
| `response.py` | 123 | `meta`/`response_type`/`data` envelope, list pagination (`limit`/`offset`/`total_count`/`has_more`), datetime serialization |
| `util.py` | 145 | Second-precision timestamp parse/format (3 fractional digits), body validators |
| `services_core.py` | 617 | Clock, corporations, bylaws (+OCC adopt/supersede), directors (seat capacity, email uniqueness, resign cascade), committees, memberships (rotation, AUDIT independence) |
| `services_meetings.py` | 712 | Meetings (overlap, notices, reschedule OCC, cancel cascade, convene quorum snapshot, adjourn→Minutes), notices, attendance, agenda, packages, tier-gated documents |
| `services_voting.py` | 909 | Resolutions (table/open/close/redraft/consent), votes (recusal→duplicate→eligibility ordering), disclosures, minutes/book/purge, audit reconstruction + digest + approval rate, checkpoint |

Total: 3,298 lines.

## Route parity
A programmatic diff of the Flask url_map against SCAFFOLD.yaml §1.5 confirmed **all 79 declared (method, path) pairs are registered, none missing**; the only extra was Flask's built-in `/static` helper, which I disabled (`static_folder=None`), leaving exactly the 79 declared endpoints. (Independently re-verified by orchestrator post-generation: 79/79, missing NONE, extra NONE.)

## Self-check results (boot smoke tests, server restarted between suites)
- Fresh boot via `bash start.sh`: HTTP-ready in ~2 s, store empty (`GET /corporations` → `total_count: 0`), default clock confirmed (first created entity stamped `2026-05-01T00:00:00.000Z`), no seeding anywhere.
- Main scenario suite: **138/138 assertions passed** — envelopes, auth/header errors, pagination bounds, bylaws OCC (`ERR_STALE_VERSION`) + supersede chain, seat-capacity boundary, duplicate email, committee below-quorum/restore, rotation boundary (round-half-up to 2 dp), calendar overlap/back-to-back, notice timeliness + waive self-scope, reschedule OCC + notice deletion, proxy rules, convene snapshot, agenda lock, ORDINARY/SPECIAL close outcomes, recast, adjourn blocking, minutes review loop + `retention_until` + gap-free `book_seq_no` + content hash, package lead window, document tier filtering (`ERR_PACKAGE_ACCESS_DENIED`), consent majority/unanimous/deadline/lapse, disclosure closed-interval overlap + clearing-resolution gate, resign/term-expiry cascades, retention purge (content erased, hash retained), audit reconstruction (gap→FAILED with retry, ordered log, digest, `governance_approval_rate_pct` per-resolution round-then-average).
- Edge suite: **15/15 passed** — rolling-quorum recovery after late arrival with the convene snapshot frozen, ABSENT voter ineligible, unanimous consent arithmetic, checkpoint-driven consent adoption, version bumps on every mutation.

Notable fidelity decisions: all entity timestamps derive from the logical clock at second precision (serialized with `.000` ms per §2.5); computed counters are stored on parents and bump `version`/`updated_at` per the §2.5 broad mutation rule (so `corporation.version` advances on director count changes, feeding the adopt OCC check); validation follows the §2.11 tier order, with the one documented exception that `open_vote` checks `ERR_MEETING_NOT_IN_SESSION` before `ERR_QUORUM_NOT_MET` per the §3.6 narrative and scaffold preconditions. Ambiguous corners were resolved as follows: propose on a locked agenda → `ERR_AGENDA_LOCKED`; package create on a wrong-state meeting → `ERR_INVALID_STATE_TRANSITION`; second ACTIVE chair → `ERR_VALIDATION`; `finalize_consent` with neither condition met → 200 unchanged; reconstruction digest = SHA-256 over `"\n"`-joined `seq|source_type|source_id|occurred_at` lines.

No other `tasks/task_*` directories and no `test_suite`/`test_helpers` content were read.

## Step 7: Run Tests and Iterate — 2026-08-10T21:51:00.000Z

All 8 parallel rounds pass: 106/106 in every round.

## Summary

**Iterations run**: 2 (1 initial sweep to surface failures, 1 verification sweep after fixes — all 8 rounds clean).

**Tests deleted**: None.

**Fixes applied to `test_helpers/`**: None.

**Fixes applied to `test_suite/`**:

- `/home/ubuntu/github/CodingPRD/tasks/task_1123_board_meeting_minute_book_administration/test_suite/test_04_notice_timeliness.py` — added `_parse_iso_second` helper and switched three `deadline_at`/`sent_at` assertions from exact string equality to parsed-datetime comparison at second precision. Rationale: PRD §2.5 mandates three-fractional-digit serialization only for `created_at`/`updated_at`/`api_request_timestamp`; PRD §2.8 says "All timestamps are compared at second precision". Exact-string assertions on derived timestamps over-specify a wire format PRD does not pin down (two PRD-faithful readers could legitimately emit `"2026-06-10T10:00:00Z"` or `"2026-06-10T10:00:00.000Z"`). Comparing at second precision is exactly what PRD prescribes. Affected tests: `test_regular_branch_uses_notice_days_regular`, `test_special_branch_uses_notice_days_special`, `test_notice_sent_exactly_at_deadline_is_timely`.

- `/home/ubuntu/github/CodingPRD/tasks/task_1123_board_meeting_minute_book_administration/test_suite/test_05_vote_outcomes.py` — `close_vote_as_chair` already unwraps via `get_success_data` and returns a `dict`; the tests were incorrectly re-wrapping it with `validate_success(resp, ...)`, causing `AttributeError: 'dict' object has no attribute 'status_code'`. Fixed by using the returned dict directly; dropped now-unused `validate_success` import. Affected tests: `test_ordinary_present_and_voting_adopted`, `test_special_full_board_majority_rejected`.

- `/home/ubuntu/github/CodingPRD/tasks/task_1123_board_meeting_minute_book_administration/test_suite/test_14_errors_misc.py` — `test_duplicate_director_email_rejected_within_corporation` referenced `create_corporation` without importing it. Added `from test_helpers import create_corporation` inside the test (matching the pattern used elsewhere in the same file).

**Fixes applied to `implementation/`**: None — all 6 failures were test-side artifacts (assertion over-specification, helper-return-shape misuse, missing import). The implementation was already PRD-faithful.

Orchestrator verification: all 8 `results.{1..8}.json` files on disk show `total=106, passed=106, failed=0, errors=0, skipped=0`.

## Step 8: Finalize PRD — 2026-08-10T21:53:30.000Z

Done. PRD_FINALIZED.md is written at `/home/ubuntu/github/CodingPRD/tasks/task_1123_board_meeting_minute_book_administration/workspace/PRD_FINALIZED.md` with exactly one inserted paragraph.

## Summary

**Line counts:** PRD.md = 359 lines; PRD_FINALIZED.md = 361 lines; delta = +2 lines (+0.56%). One edit total.

**Changes:**
- §2.5 (Common Resource Properties) — insert — added a paragraph generalizing the three-fractional-digit ISO 8601 UTC serialization format from just `created_at`/`updated_at` (and §2.2's `api_request_timestamp`) to every timestamp the server emits in a response body, naming the derived/lifecycle fields (`sent_at`, `deadline_at`, `waived_at`, `convened_at`, `recorded_at`, `sealed_at`, `distributed_at`, `cast_at`, `closed_at`, `adopted_at`, `cleared_at`, `approved_at`, `retention_until`, `consent_deadline_at`, `current_utc`, `occurred_at`) and cross-referencing §2.8's second-precision comparison rule — impl: `workspace/implementation/util.py:38-47` (`iso_ms`), `workspace/implementation/response.py:23-30` (`serialize_value`).

**Step-7-diff disposition:** Of the three test-suite fix groups, only the `test_04_notice_timeliness.py` item was PRD-relevant (wire format of derived timestamps was under-pinned). The `test_05_vote_outcomes.py` and `test_14_errors_misc.py` items were pure test-harness bugs (helper-return-shape misuse, missing import) with no PRD implication — no edits made for them. No implementation fixes and no test deletions occurred, so there was nothing else to trace.

**Per-edit pre-edit search log:**

Edit 1 (§2.5 timestamp-format paragraph):
- (a) **Subject:** wire format of server-emitted timestamps beyond `created_at`/`updated_at`/`api_request_timestamp` — concretely, `deadline_at`/`sent_at` from the test_04 site.
- (b) **Impl paths enumerated and read/grepped:** `util.py` (full file: `iso_ms`, `truncate_second`, `parse_datetime`, `wall_now_iso_ms`); `response.py` (full file: `serialize_value`, `serialize_row`, `_meta`, `_filter_value`, `list_response`); `db.py:13-22` (clock storage); `services_core.py:175-178` (`set_current_utc` → `current_utc` via `iso_ms`) and grep for all `iso_ms`/`serialize_row` call sites across `services_core.py`, `services_meetings.py`, `services_voting.py`; `services_meetings.py:140-183` (notice creation: `sent_at`/`deadline_at`/`is_timely`), `services_meetings.py:332-335` (`is_timely` re-derivation on read); `services_voting.py:760-839` (reconstruction log: `occurred_at` via `iso_ms`, including digest lines); grep for `strftime`/`isoformat`/`%Y-%m-%d` across all impl files to confirm no alternative serializer exists (only `util.py:47` hits).
- (c) **Wording adjustment:** Enumeration showed the impl serializes *all* response-body datetimes (including the clock endpoint's `current_utc` and the reconstruction log's `occurred_at`, which are not resource properties) through the same 3-fractional-digit format, so the sentence was scoped to "every timestamp the server emits in a response body" rather than to resource fields only, and the field list was made illustrative ("such as") rather than exhaustive. A closing clause defers comparison semantics to §2.8 so the new sentence cannot be read as narrowing the second-precision comparison rule or claiming anything about storage internals.

## Step 9: Complete PRD — 2026-08-10T22:05:00.000Z

All edits are in place. The line-count delta is +1 (the §2.11 tier list gained one numbered tier; all other edits were in-paragraph). Char-delta: 63694 − 60580 = +3114.

## Exit Summary

**Source:** `PRD_FINALIZED.md` (361 lines, 60,580 chars) → **PRD_COMPLETED.md** (362 lines, 63,694 chars). Char-delta: **+3,114**.

**Counts:** 20 ambiguity-pins, 1 mismatch-revision (21 changes total; the §2.11 OCC-tier insert also renumbered tiers 7–9 → 8–10 as part of the same revision).

**Changes:**

- §2.3 — insert — ambiguity — list default sort ties (shared logical-clock `created_at`) break by creation/insertion order — implementation/response.py:107 (sort key `(created_at, _seq)`)
- §2.4 — insert — ambiguity — clock capability accepts any well-formed timestamp; no monotonicity constraint, backward sets allowed — implementation/services_core.py:175-178
- §2.11 tier 4 — insert — ambiguity — ownership checks needing the target resource are evaluated after it loads, so a nonexistent target reports `ERR_NOT_FOUND` — implementation/services_core.py:406-408, implementation/services_meetings.py:360-362
- §2.11 new tier 6 — insert — ambiguity — OCC staleness (`ERR_STALE_VERSION`, `ERR_STALE_MEETING_VERSION`) sits after the state tier and before the clock-relative temporal tier; former tiers 6–9 renumbered 7–10 — implementation/services_core.py:282-289, implementation/services_meetings.py:194-206
- §3.1 — revise — mismatch — `incorporation_state` "two-letter code" wording softened: stored exactly as supplied with no format validation — implementation/services_core.py:186-199 (`req_string` only, no length check)
- §3.3 — insert — ambiguity — adding a membership to a `DISSOLVED` committee is `ERR_INVALID_STATE_TRANSITION` — implementation/services_core.py:544-545
- §3.3 — insert — ambiguity — seating a second `ACTIVE` chair is rejected with `ERR_VALIDATION` (HTTP 400) — implementation/services_core.py:556-563
- §3.4 — insert — ambiguity — `duration_minutes` is an integer of at least 1 at meeting creation — implementation/services_meetings.py:83-85
- §3.4 — insert — ambiguity — `duration_minutes` minimum 1 applies at reschedule as well — implementation/services_meetings.py:188-190
- §3.4 — insert — ambiguity — meeting cancellation admits any `BoardChair`-role caller (no `chair_director_id` comparison) — implementation/services_meetings.py:227-228, implementation/app.py:266-269
- §3.4 — insert — ambiguity — a meeting may hold multiple board packages; cancellation withdraws every `ASSEMBLING`/`SEALED` one — implementation/services_meetings.py:249-252, 550-570
- §3.4 — insert — ambiguity — attendance may be recorded for a director of the corporation in any status, not only `ACTIVE` — implementation/services_meetings.py:404-409 (only cross-corporation is checked)
- §3.5 — insert — ambiguity — proposing an agenda item on a meeting past `NOTICED` fails with `ERR_AGENDA_LOCKED`, same as inclusion — implementation/services_meetings.py:473-474
- §3.5 — insert — ambiguity — distribution with neither a pinned nor a currently adopted bylaws is refused with `ERR_NO_ADOPTED_BYLAWS` — implementation/services_meetings.py:622-628
- §3.6 — insert — ambiguity — opening, closing, and withdrawing a floor vote admit any `BoardChair`-role caller; chair-identity comparison applies only to convene, adjourn, and minutes approve/reject — implementation/services_voting.py:137-144, 156, 190
- §3.6 — insert — ambiguity — the recusal obligation is re-evaluated at recast time (`ERR_CONFLICT_RECUSAL_REQUIRED` for non-RECUSED recast by a conflicted caster) — implementation/services_voting.py:438-443
- §3.6 — insert — ambiguity — vote records list with `resolution_id`, `director_id`, `channel`, and `status` filters — implementation/services_voting.py:406-416
- §3.7 — insert — ambiguity — when neither consent finalization condition holds, the call is a no-op returning the unchanged resolution — implementation/services_voting.py:282-299
- §3.9 — insert — ambiguity — `retention_until` advances `approved_at` by calendar-anniversary years, clamping Feb 29 → Feb 28 on non-leap target years — implementation/util.py:59-65, implementation/services_voting.py:625-626
- §3.9 — insert — ambiguity — approving minutes with no adopted bylaws leaves `retention_until` null and such minutes are never purged — implementation/services_voting.py:624-629, 890-896
- §3.9 — insert — ambiguity — reconstruction residual ties after (timestamp, source-type rank, `created_at`) break by creation/insertion order; also pinned that failure nulls `reconstruction_digest`/`entry_count`/`governance_approval_rate_pct` and success clears `failure_reason` on retry — implementation/services_voting.py:765-772, 780-805, 845
- §3.9 — insert — ambiguity — `governance_approval_rate_pct` is null when no in-scope closed resolution contributes a percentage — implementation/services_voting.py:826-838

Items analyzed and deliberately left unchanged (PRD already uniquely pinned or §2.9/§2.1 generic rules cover them): frozen `_eligible_pool_at_close` as the reading of "ACTIVE at `closed_at`", agenda-proposal ownership (§2.1's enumeration excludes it), send-notices within-tier order (PRD prose order matches impl), non-PROXY records carrying a `proxy_holder_director_id`, 405→`ERR_NOT_FOUND` mapping, and `active_director_count` floor-at-zero.

File produced: `/home/ubuntu/github/CodingPRD/tasks/task_1123_board_meeting_minute_book_administration/workspace/PRD_COMPLETED.md`.

Orchestrator verification: PRD_COMPLETED.md on disk at 362 lines / 63,694 chars (79 diff lines vs PRD_FINALIZED.md).
