# Worklog — task_0154_itsm_helpdesk

Scenario: IT Service Management Helpdesk: ticket/category/priority, SLA/OLA timer, assignment group/queue, change request (CAB approval), problem/known error, knowledge-base deflection, CSAT, asset linkage

Difficulty: Expert (§0.4 Expert band) — passed to Step 2 (scaffold-generator) only.

## Step 1: Create task directory — 2026-06-04T18:42:00.000Z

Created `tasks/task_0154_itsm_helpdesk/` and `tasks/task_0154_itsm_helpdesk/workspace/` (pre-allocated path per orchestration override; no auto-scan). Verified `./INSTRUCTION.md` exists for Step 3 copy.

## Step 2: Generate scaffold (Expert band) — 2026-06-04T18:42:00.000Z

All three files present and lint-clean (`scaffold_lint.py` → VERDICT: clean lint, 327 calls scanned, all FK reverse-reachability satisfied):
- SCAFFOLD.yaml (1714 lines), SCAFFOLD_DIFFICULTY_DESIGN.yaml (1032 lines), SCAFFOLD_CORNER_DESIGN.yaml (1180 lines)

Counts:
- Entities: 11 — Category, SlaPolicy, AssignmentGroup, Ticket (central), Problem, KnownError, KbArticle, ChangeRequest, CabVote (append-only event), CsatSurvey, Asset
- State machines: 5 — Ticket (cyclic lifecycle + reopen loop), SlaTimer (parallel/independent SLA dimension on the ticket), ChangeRequest (CAB branching fork-join), Problem (lifecycle + known-error promotion), Asset (CI status). Plus 2 OCC concurrency rules.
- Calculations: 11 — incl. 5 headline rules (dual-variant sla_due_dates, dual-variant cab_tally, combinatorial sla_effective_resolve_window, nested-rounding group_load_score, ordered csat_index)
- Validations: 17 (priority-ordered, 8 categories)
- Endpoints: 52 (31 POST / 21 GET, incl. 2 /_clock test-driving endpoints)
- Error catalog: 17
- Roles: 5 — Requester, Agent, ChangeManager, CabMember, PlatformAdmin (segregation-of-duties + peer model; all identity: opaque)

Expert-band: 9 §0.5 difficulty rules × 2 instances each (18 total); §1.9 corner design = 28 active instances + 2 excluded_because stubs across 7 sections. Deliberate overage: 52 endpoints > nominal Expert ceiling (20–32), driven by 12-transition Ticket lifecycle + mandatory FK reverse-reachability GETs — accepted as lint-clean. Trimmed a redundant TicketAssetLink junction entity (Ticket.asset_id already expresses asset linkage).

## Step 3: Copy INSTRUCTION.md — 2026-06-04T18:42:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_0154_itsm_helpdesk/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-04T18:42:00.000Z

Generated `workspace/PRD.md` (265 lines). Sections: §1 Introduction, §2 Global Specifications (9 subsections: RBAC/5 roles, response structure, pagination, identity/timestamps/versioning incl. CabVote common_fields:false exception, nested retrieval & FK resolution, computed fields & cascades, OCC, SLA clock & test time source, numeric precision & rounding), §3 Business Logic (10 scattered subsections), §4 Endpoint table (53 rows), §5 Error catalogue (17 IDs).

Contract results: Field-Name Coverage 70/70 PASS (added missing resolution_note to §3.6); Rule Coverage PASS (both OCC rules, 17-rule priority ordering, CAB quorum/veto, dual-variant SLA due-date no-re-anchor, combinatorial calcs incl. order-pinned group_load_score + 4-step CSAT empty-set boundary, inclusive SLA boundaries, cross-entity cascades); §3 Path Purity PASS (364 tokens, 0 slash-paths/bare-methods). Confirmed: neither design YAML read; no sibling tasks consulted.

## Step 5: Generate unit tests — 2026-06-04T18:42:00.000Z

test_helpers/ (9 files): types.py (CabVote carries only id+created_at per append-only rule), api_client.py (56 endpoint methods), api_errors.py (17 error IDs + HTTP-status map), assertions.py, factories.py, constants.py (1440/2880-min windows, 60-min reopen penalty, CAB quorum, priority weights), test_users.py (all 5 roles opaque → shared-constant headers + inline requester/change_manager/cab_member builders), fixtures.py (catalog → ticket progression → CR lifecycle → known-error/linked-ticket chains + clock helpers), __init__.py.
test_suite/: 10 files, 63 test functions. Queue A (Difficulty): 36 tests covering all 18 instances ×2 each (no shortfalls). Queue B (Corner): 27 tests over 27 of 28 non-stub instances.
Instances skipped (1): Corner/endpoints/list_change_requests_filtered_by_ticket_id_reverse_reachability — PRD-first filter failure (no verbatim PRD sentence names a ticket_id query filter on GET /change-requests; §4 row says only "List change requests", §2.3 covers only generic limit/offset). Left as documented gap, no placeholder. 2 excluded_because stubs not translated.
Audits: every docstring ends with exactly one verbatim Design: tag; all 18 queue-A ≥2 tests; all covered queue-B ≥1; PRD citations verbatim; no skip/xfail; 56 api_client/fixture/factory symbols resolve; 63 tests collect with zero import/syntax errors.

## Step 6: Generate implementation — 2026-06-04T18:42:00.000Z

Python + Flask in workspace/implementation/. Files: start.sh (guarded foreground exec launcher), requirements.txt (flask==3.0.3), app.py (host 0.0.0.0, port $PORT, threaded), db.py (in-memory dicts + test-driving logical clock), errors.py (ApiError + 17-error catalog), response.py (meta/response_type/data envelope, req_ ids, 3-digit ISO timestamps), middleware.py (X-User-ID/X-User-Role auth + RBAC, 401-before-403), routes/ (config, tickets, problems, changes, csat), services/ (common, sla, serialize).
Endpoint count: 52 method+path endpoints matching PRD §4. start.sh reads $PORT (default 10000), installs deps only when `import flask` fails (guarded so per-test reboots skip pip), then exec python3 app.py foreground on 0.0.0.0; boots in ~0.6s. Storage in-memory only, total_count==0 on fresh boot, NO seeding.
Smoke tests passed: SLA provisional/final due-dates + pause/resume credit + reopen +60m + inclusive <= boundary; CAB SoD(403)→OCC(412)→dup-vote(409) ordering, quorum-by-risk, approve/reject-veto, bubble-up cascade resuming gated ticket; group_load_score pinned rounding; csat_index 4-step empty→0.0; clock set(no retro-breach) vs advance(fires breach); deflection auto-cancel + counter bumps; problem→known-error→resolve with asset DEGRADED↔OPERATIONAL cascade; validation ordering (enum 422 vs missing-field 400).
Spec note flagged by impl-gen: scaffold Ticket state machine models `route` as NEW→ASSIGNED (enforced valid only from NEW); PRD prose frames routing loosely as "moving between queues" but pins no other source state — followed the state machine.

## Step 7: Test-and-fix loop — 2026-06-04T18:42:00.000Z

Final verification: all 8 results.{1..8}.json green at passed=62 total=62 failed=0.

(subagent summary verbatim)

**Iterations run:** 6 sweeps (8 parallel rounds each = 48 rounds total). Final two sweeps both green at 62/62, 0 failed, 0 errors.

**Tests deleted (1):**
- `test_resolve_excludes_ticket_from_problem_linked_count` (test_06_temporal_windows.py) — **unique-derivability collapse (STEP 1b)**. It asserted that resolving a linked ticket drops the problem's `linked_ticket_count` to 0, but PRD §3.8 defines that counter verbatim as "counting only those linked tickets whose `lifecycle_state` is not `CLOSED` or `CANCELLED`" — RESOLVED is *not* in the exclusion set, so a faithful PRD-only implementer keeps the RESOLVED ticket counted (stays 1). The test's own docstring quoted that exclusion set yet asserted the opposite outcome. PRD covers the counter but admits both readings, so it cannot uniquely determine RESOLVED-exclusion. (Scaffold rule that drove it: Difficulty/compensating_invariant/link_then_close_conserves_problem_linked_ticket_count.)

**Fixes applied to test_suite/ (1):**
- `test_06_temporal_windows.py` — `test_link_then_close_returns_linked_ticket_count_to_zero`: added `fx.advance_clock(1441)` between resolve and close. **STEP 2 test bug** — PRD §3.6 requires the close precondition (reopen window strictly elapsed, i.e. >1440 min past `resolved_at`, OR a survey exists); the test closed immediately without satisfying it, so the PRD-faithful implementation correctly returned ERR_INVALID_STATE. Advancing past the 1440-minute window makes the setup PRD-faithful (CLOSED is then excluded from the count → 0).

**Fixes applied to implementation/ (1 logic + 2 boot-reliability):**
- `routes/tickets.py` `route_ticket()` — **STEP 3 logic fix**. Removed `rec["lifecycle_state"] = "ASSIGNED"` on route. PRD §3.3 prose describes routing as only writing `assignment_group_id`, recomputing queue depths, and optionally starting the OLA leg — it does **not** transition lifecycle_state (only Assigning advances NEW→ASSIGNED). The bogus transition made a second route hit the state check (ERR_INVALID_STATE) instead of the OCC check, so `test_route_with_stale_ticket_version_rejected` couldn't reach ERR_STALE_VERSION. (Note: SCAFFOLD.yaml models route as NEW→ASSIGNED, but PRD prose is authoritative on semantic conflict, and the OCC test confirms the no-transition reading.)
- `app.py` — added a bind-retry loop around `app.run` (retries OSError for up to 20s) and silenced the werkzeug access logger, to harden boot under the 8× parallel per-test-reboot storm.
- `start.sh` — replaced the per-reboot `python3 -c "import flask"` dependency probe with a filesystem sentinel (`.deps_ok`). The probe spawned a second interpreter on every reboot; under the ~15s per-test restart budget × 8 simultaneous boots this was the dominant cause of the near-deterministic "could not be restarted" boot flake on `test_cab_approve_branch_approves_change_for_low_risk_quorum_one`. The sentinel runs the check once, then every reboot execs straight to the app. This eliminated all boot flakes — both confirmation sweeps were fully clean (`.deps_ok` is a build artifact, not seeded entity data; in-memory-only storage rule is preserved).

## Step 8: Finalize PRD — 2026-06-04T18:42:00.000Z

PRD_FINALIZED.md created (265 lines, byte-identical to PRD.md — 0-line / 0% delta). No edits required: every Step 7 diff item is a case where PRD prose already uniquely and correctly determines the (fixed) implementation's behavior.
- Deleted test (linked_ticket_count RESOLVED-exclusion): not a PRD silence — PRD §3.8 already states the exclusion set is CLOSED/CANCELLED only (RESOLVED stays counted), matching services/common.py:101. Test was self-contradictory.
- Test fix (advance_clock(1441) before close): pure fixture bug — PRD §3.6 already pins close precondition (resolved_at+1440 strictly elapsed OR survey exists), matching routes/tickets.py:408-411. No PRD surface.
- Impl fix (route no longer sets lifecycle_state=ASSIGNED): fix brought code into alignment with EXISTING PRD §3.3 (routing writes assignment_group_id + queue depths + optional OLA leg, no lifecycle transition; only Assigning advances NEW→ASSIGNED), matching routes/tickets.py:182-193. app.py bind-retry + start.sh .deps_ok are boot-reliability only, no PRD surface.
Pre-edit search log recorded for all 3 subjects (routing→lifecycle_state, linked_ticket_count exclusion set, close precondition/reopen window); all enumerated impl paths consistent with existing PRD prose → no wording adjustments.

## Step 9: Complete PRD — 2026-06-04T18:42:00.000Z

PRD_COMPLETED.md produced from PRD_FINALIZED.md (265 lines / 40135 chars → 265 lines / 42585 chars; +2450 chars, all in-paragraph; 11 paragraphs revised). Counts: 9 ambiguity-pins, 3 mismatch-revisions.
Changes (full-impl scan, impl is sole authority):
- §2.3 Pagination — insert — pinned limit<1→1, negative offset→0 clamps; non-integer limit/offset → ERR_VALIDATION (services/common.py:36-55).
- §3.1 SLA policy — revise — mismatch — PRD claimed resolve>=response constraint; impl only checks integer type, rejects nothing else (routes/config.py:101-103).
- §3.1 category active — revise — mismatch — PRD claimed active gates ticket open; impl stores/echoes but never gates (routes/tickets.py no active check).
- §3.2 Deflection — insert — both accept_deflection true AND kb_article_id required; unresolvable kb_article_id → ERR_FK_NOT_FOUND (routes/tickets.py:82-85,124).
- §3.3 Triage/routing — insert — assign and route both require NEW; routing ERR_INVALID_STATE precedes OCC; route does not change lifecycle_state (routes/tickets.py:174-179,199-211).
- §3.3 Reprioritize — insert — final-variant resolve_due_at re-adds reopen penalty (reopen_count×60); not state-gated (services/sla.py:61-64).
- §3.4 First response — insert — met response leg leaves sla_state unchanged (stays RUNNING; no response-met value) (routes/tickets.py:226-231).
- §3.5 Attach change — insert — missing change → ERR_FK_NOT_FOUND; non-IN_PROGRESS ticket or wrong-ticket/wrong-state change → ERR_INVALID_STATE (routes/tickets.py:307-313).
- §3.5 CAB voting — insert — voting on change not in PENDING_CAB → ERR_INVALID_STATE before OCC (routes/changes.py:133-138).
- §3.6 Reopen — insert — ordered error chain state → reopen-window → ownership ERR_FORBIDDEN (routes/tickets.py:374-383).
- §3.6 Cancel — insert — ownership mismatch → ERR_FORBIDDEN, after NEW-state check (routes/tickets.py:425-428).
- §3.7 CSAT survey — insert — survey against never-resolved ticket → ERR_CSAT_WINDOW_CLOSED (routes/csat.py:32-36).
- §3.7 CSAT index — insert — zero denominator → response_rate 0.0, avg_score still computed from eligible surveys (services/sla.py:140-146).
Left unpinned (deliberate): list-endpoint extra filter query params and internal ola_due_at timer — neither is a serialized/observable field nor suite-exercised.

## Pipeline complete — 2026-06-04T18:42:00.000Z

All 9 steps done. Final state: 62/62 tests green across all 8 results.{1..8}.json. Artifacts present: SCAFFOLD.yaml (+2 design YAMLs), workspace/{PRD.md, PRD_FINALIZED.md, PRD_COMPLETED.md, INSTRUCTION.md, implementation/}, test_suite/ (10 files, 62 tests), test_helpers/ (9 files).
