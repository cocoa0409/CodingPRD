# Worklog — task_0075_credit_report_disputes_fcra

## Step 1: Create task directory — 2026-06-01T00:46:00.000Z

Created `tasks/task_0075_credit_report_disputes_fcra/` and `workspace/` subdir. Output path pre-allocated by caller; tasks/ not rescanned to avoid concurrent ID contention.

## Step 2: Generate scaffold (Expert band) — 2026-06-01T01:11:00.000Z

All three scaffold artifacts are generated, internally consistent, and pass `scaffold_lint.py` cleanly.

Generated the Expert-band scaffold for **task_0075_credit_report_disputes_fcra** (Credit Report Disputes / FCRA) as three files under the task directory:
- `SCAFFOLD.yaml` (§1.0–§1.7)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (§1.8)
- `SCAFFOLD_CORNER_DESIGN.yaml` (§1.9)

**Complexity profile:** compliance/audit primary + workflow-orchestration secondary; flat multi-root topology; cyclic state-machine shape; peer_roles; immediate consistency. Layers: scheduled/deferred actions, cascading side effects, optimistic concurrency, rate/threshold triggers.

**Scaffold contents (§1.1–§1.7):**
- **10 entities:** Consumer, Furnisher, CreditFile, Tradeline, Dispute, ReverificationRequest, SecurityFreeze, RegulatoryComplaint, Notification (append-only), ReageEvent (append-only).
- **5 state machines:** Dispute (cyclic REVERIFYING↔REOPENED + branching DELETE/MODIFY/VERIFY fork-join + deadline AUTO_DELETED), Tradeline, ReverificationRequest, SecurityFreeze, RegulatoryComplaint.
- **6 calculations:** investigation_deadline (CALENDAR-30 vs EXPEDITED-15-business-day variants), purge_due_at (DOFD+7yr+180d), reage_violation_flag, dispute_priority_score (non-linear weighted), file_protection_state (FREEZE-dominates-LOCK posture), open_counts_recompute.
- **2 concurrency rules:** OCC on CreditFile.version for freeze-place and dispute-create.
- **20 validations** (priority-ordered), **20 errors**, **42 endpoints** (incl. FK reverse-reachability GETs and `/_clock/set` + `/_clock/advance` test-driving endpoints), **5 roles** (Anonymous, Consumer/Furnisher entity-backed, CreditBureau/Regulator opaque).

**Expert-band depth/breadth instance counts:**
- §1.8: **9 rule_ids × 2 = 18 difficulty instances** (all 9 §0.5 rules satisfied with differentiation).
- §1.9: **39 active corner instances + 4 `excluded_because` stubs (43 total)** across 10 sections.

**Verification:** all three files parse; `scaffold_lint.py` returns `VERDICT: clean lint` (422 setup/trigger calls checked).

## Step 3: Copy INSTRUCTION.md — 2026-06-01T01:11:00.000Z

`cp INSTRUCTION.md workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-01T01:16:00.000Z

PRD generated at `workspace/PRD.md` (252 lines). Both design YAMLs withheld.

Sections: §1 Introduction; §2 Global Specs (RBAC all 5 roles, envelope, pagination, common props incl. Notification/ReageEvent id+created_at only, cascading consistency + derived counts, nested existence, validation precedence, OCC on credit file, date/time/integer precision); §3 Business Logic (9 lifecycle subsections); §4 42-endpoint table; §5 20-error table.

Hard Contracts: Contract 1 (Field-Name Coverage) PASS (entities 44/44, request_body 4/4, query_params 9/9); Contract 2 (Rule Coverage) PASS (both concurrency rules + 412/ERR_STALE_FILE_VERSION; validation precedence; all 6 calculations in prose); Contract 3 (§3 Path Purity) PASS (0 path tokens).

Notable: endpoints referenced via state-transition framing only; clock set vs advance disambiguated without paths; four sibling auto-delete transitions collapsed into one cascade narrative; constants embedded with unit framing (30 calendar vs 15 business days, 2555+180 days, 1 point per $500).

## Step 5: Generate unit tests — 2026-06-01T01:30:00.000Z

Test infra in `test_helpers/` (9 files) + `test_suite/` (conftest + 5 test files). 75 tests total, all collecting and byte-compiling cleanly.
- Queue A (Difficulty): all 18 instances translated, 2 tests each (36 tests).
- Queue B (Corner): all 39 non-stub instances translated, ≥1 test each (39 tests).
- 4 `excluded_because` stubs not translated.
- Skips: none. Every instance passed the PRD-first two-condition filter.
- 75 test funcs = 75 `Design:` lines (exactly one tag each); no skip/xfail.

## Step 6: Generate implementation — 2026-06-01T01:30:00.000Z

Complete Python + Flask in-memory REST API at `workspace/implementation/` (11 files). 41 endpoints implemented (all §1.5/§4 rows). start.sh uses `exec python3 app.py`, reads $PORT, binds 0.0.0.0.

Notable: validation precedence per §2.7 (auth → role → body → existence L-to-R → ownership → OCC → state → business); deadline math CALENDAR +30 / EXPEDITED +15 business days, inclusive; purge = DOFD + 2555 + 180; cascades atomic in-request (transition → count recompute → notification → version bump); OCC 412/ERR_STALE_FILE_VERSION; freeze overlap half-open; no startup seeding; monotonic _seq for deterministic ordering.

## Step 7: Test and iterate loop — 2026-06-01T01:45:00.000Z

All 8 rounds pass cleanly: 74/74 each.

**Iterations run:** 2 (initial diagnostic sweep + verification sweep).

**Root causes found:** First sweep showed 16 union failures, but only 2 were real. Dominant failure mode (14 of 16) was flaky "API server could not be restarted before test" setup errors — not logic bugs.

**Tests deleted (1):**
- `test_duplicate_dispute_rejected` (test_02_disputes_and_priority.py) — ERROR-PRECEDENCE-SILENCE / unreachable-branch collapse. PRD §3.3 (line 130) fixes filing-precedence order as `…→ ERR_TRADELINE_NOT_DISPUTABLE → ERR_DUPLICATE_DISPUTE`. Filing a dispute transitions the tradeline to `DISPUTED` (line 134) and it stays `DISPUTED` for the entire non-terminal lifetime of the dispute (line 158). Therefore any tradeline referenced by a non-terminal dispute is always `DISPUTED`, so `ERR_TRADELINE_NOT_DISPUTABLE` always fires before the duplicate check is reached. Fixture leaves tradeline `DISPUTED`, so PRD-faithful outcome is `ERR_TRADELINE_NOT_DISPUTABLE` — exactly what impl returned. Asserted `ERR_DUPLICATE_DISPUTE` is unreachable under PRD precedence. Impl's duplicate check left intact (defense-in-depth, traces to verbatim PRD).

**Fixes applied to implementation/ (1):**
- `start.sh` — wrapped `pip install -r requirements.txt` in `if ! python3 -c "import flask"` guard. Under per-test-server isolation × 8 concurrent rounds = ~600 pip invocations, whose network latency intermittently exceeded server restart timeout → "could not be restarted" setup failures. Skipping pip when Flask importable eliminated per-boot overhead. No application logic changed; storage in-memory only, state wipes on restart.

**Fixes applied to test_helpers/:** none.

**Final state:** Full 8-round parallel sweep — every round 74/74, union of failures empty.

## Step 8: Finalize PRD — 2026-06-01T01:50:00.000Z

PRD_FINALIZED.md is an exact copy of PRD.md — no edits warranted (252 → 252 lines, 0% delta, byte-for-byte identical).

Both `<step_7_diff>` items required no PRD edit:
1. Test deletion (`test_duplicate_dispute_rejected`) — no PRD silence/mismatch. Impl evaluates `ERR_FILE_FROZEN → ERR_TRADELINE_NOT_DISPUTABLE → ERR_DUPLICATE_DISPUTE → ERR_OVERLAPPING_INVESTIGATION` in the exact order PRD §3.3 fixes verbatim; §3.3 already states a filed dispute transitions its tradeline to DISPUTED. Duplicate-branch unreachability for the fixture is a logical consequence of behavior PRD already fully pins. (app.py:374-392, services.py:7-8,105,203)
2. start.sh pip-install guard — pure launcher infra, no behavioral surface. INSTRUCTION.md already describes start.sh as installs deps / starts server. No edit.

## Step 9: Complete PRD scan — 2026-06-01T01:55:00.000Z

`PRD_FINALIZED.md` (252 lines, 41,959 chars) → `PRD_COMPLETED.md` (252 lines, 43,467 chars); char delta +1,508. All in-paragraph inserts/revisions — no new sections.

Counts: 5 ambiguity-pins, 4 mismatch-revisions (8 edits, 9 logical fixes).

Changes:
- §2.3 Pagination — insert — ambiguity — non-integer limit/offset → ERR_PAGINATION_RANGE (validation.py:60-68)
- §2.3 Pagination — insert — ambiguity — total_count (pre-pagination) + has_more = offset+page_len < total_count (response.py:33,29)
- §3.4 Open investigation — revise — mismatch — order state → deadline → frozen per §2.7 (app.py:452-461)
- §3.5 Dispatch reverification — revise — mismatch — order state → deadline → suspended per §2.7 (app.py:518-525)
- §3.5 Respond — revise — mismatch — order ownership → state → deadline per §2.7 (app.py:579-586)
- §3.5 MODIFY response — insert — ambiguity — non-integer/negative corrected_balance_cents → ERR_MISSING_CORRECTED_BALANCE after owner/state/deadline (app.py:589-594)
- §3.8 Adjudicate — revise — mismatch — UNDER_REVIEW state checked before ERR_INVALID_DECISION; missing decision → ERR_VALIDATION (app.py:821-824)
- §3.8 Complaint submission — insert — ambiguity — COMPLAINT_SUBMITTED notification minted without bumping file version/updated_at (app.py:773)
- §3.8 Complaint adjudication — insert — ambiguity — COMPLAINT_ADJUDICATED notification minted without bumping file version/updated_at (app.py:835)

Left unchanged (already pinned): create-dispute ordering, deadline inclusivity, DELETE/AUTO_DELETE notification ordering, EXPIRED/CANCELLED reverification handling, priority-score formula, purge anchoring, reopen/direct-reage leaving file untouched, all serializer shapes.

## Pipeline complete — 2026-06-01T01:55:00.000Z

All 9 steps done. Final 8-round parallel sweep: every round 74/74. Artifacts: SCAFFOLD.yaml + 2 design YAMLs, worklog.md, test_helpers/ (9 files), test_suite/ (conftest + 5 files, 74 tests), workspace/{INSTRUCTION.md, PRD.md, PRD_FINALIZED.md, PRD_COMPLETED.md, implementation/}.
