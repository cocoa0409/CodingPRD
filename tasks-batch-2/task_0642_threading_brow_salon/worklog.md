# Worklog — task_0642_threading_brow_salon

Scenario: Threading & Brow Salon: walk-in queue & quick-service menu, technician & chair, membership/package, add-on (tint/wax), retail, sanitation/license, loyalty, no-show
Difficulty: Expert

## Step 1: Create Task Directory — 2026-06-23T17:13:47.000Z

Task directory tasks/task_0642_threading_brow_salon was pre-assigned and already exists (workspace/ present). Did not scan ./tasks/ for next index per CRITICAL FOLDER RULE. Using this directory as {task_dir} for all steps.

## Step 2: Generate Scaffold — 2026-06-23T17:38:44.000Z

All three scaffold artifacts are generated, internally consistent, and pass `scaffold_lint.py` with a clean verdict.

Generated the Expert-difficulty scaffold for **Threading & Brow Salon**. All three required files written:
- `SCAFFOLD.yaml` (§1.0–§1.7, no design keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (single key `scaffold_difficulty_design`)
- `SCAFFOLD_CORNER_DESIGN.yaml` (single key `scaffold_corner_design`)

**Metrics (Expert band):**
- **Entities: 12** — Salon, Technician, Chair, Member, ServiceMenuItem, AddOn, RetailProduct, MembershipPackage, QueueTicket, ServiceVisit, VisitLineItem, LoyaltyLedgerEntry (target 10–15).
- **Endpoints: 53** — above the 20–32 guideline; overage comes from FK reverse-reachability GETs the lint mandates for a 12-entity flat topology.
- **Error codes: 39** — slightly above 18–30; all distinct, domain-specific, triggerable (10 are per-entity not-found errors).
- **Calculation variants: 3** declared variants across 5 calculations (visit_estimate_total/provisional, finalize_settlement/final, no_show_strike_score/instantaneous).
- **State machines: 6** — Salon, QueueTicket (cyclic WAITING↔CALLED), ServiceVisit (parallel service_status × payment_status), Chair (occupancy+sanitation cycle), MembershipPackage (cyclic ACTIVE↔DEPLETED), VisitLineItem.

**Difficulty design:** all 9 §0.5 rules covered with ≥2 instances each (19 total ≥ 18 minimum). **Corner design:** 42 instances (37 active + 5 `excluded_because` stubs).

**Key design notes:** quota/allocation archetype (finite chair+technician pool) + temporal-windowing secondary; flat topology under `api_prefix: /salon-svc`; peer-roles RBAC (SalonManager, FrontDeskAgent, Technician, Member). One OCC concurrency rule (`seat-visit-stale-salon` on Salon.version, 412). All formula-derived asserts pre-computed as literals. Final `scaffold_lint.py` verdict: clean (544 calls scanned, 0 violations).

## Step 3: Copy Shared Files — 2026-06-23T17:39:02.000Z

Copied ./INSTRUCTION.md → tasks/task_0642_threading_brow_salon/workspace/INSTRUCTION.md (1424 bytes).

## Step 4: Generate PRD — 2026-06-23T17:43:54.000Z

PRD complete and verified. Output written to workspace/PRD.md (292 lines, 42914 bytes).

**Sections covered:** §1 Introduction; §2 Global Specs (10 subsections: RBAC 4 roles + identity translation, Response Structure, Pagination, Common Properties, Logical Clock, Nested Retrieval, Validation Ordering, Monetary/Precision basis-points, OCC on Seating, Compensating Cascades); §3 Business Logic (9 subsections by lifecycle); §4 Endpoint table (all 53 endpoints); §5 Error catalogue (all 39 error codes).

**Hard Contract verification (all PASS):** Contract 1 Field-Name Coverage 73 identifiers 0 missing; Contract 2 Rule Coverage all 39 error IDs + 36 state/enum values + OCC rule + calc constants (five-cents point value, 10000 bps divisor, tier credits 4/8/12, discount 500/1000/1500 bps, suspend-at-2/ban-at-4, recall limit 2) + settlement order + provisional/final variants + void cascade all in prose; Contract 3 §3 Path Purity 431 tokens scanned, 0 slash-prefixed/bare-method/method+path. Withheld design files not opened; no sibling tasks read.

## Step 5: Generate Unit Tests — 2026-06-23T18:07:50.000Z

Both test_helpers/ and test_suite/ written and verified.

- `test_helpers/` — 9 files: types.py, api_client.py (57 endpoint methods), api_errors.py (40 error IDs), assertions.py, factories.py, constants.py, test_users.py (opaque SalonManager/FrontDeskAgent + entity-backed Technician/Member builders), fixtures.py (tiered composite setups incl. setup_divergence_visit, setup_seated_visit, drive_member_to_strikes), __init__.py.
- `test_suite/` — conftest.py + 6 domain test files (salon/catalog, queue, seating/resources, visit lifecycle, void/compensation, priority/RBAC).

**Test counts:** 73 test functions across 6 files. Every test carries exactly one `Design:` tag (73/73, no untagged/dual-tagged). All modules import + collect cleanly.

**Queue-A (Difficulty):** all 19 instances across 9 rules covered ≥2 tests each (38 tags). **Queue-B (Corner):** all 37 non-stub instances minus 2 deliberate skips = 35 covered. 5 `excluded_because` stubs not translated.

**Instances skipped (2):**
- `Corner/state_machines/cancel_already_cancelled_ticket_terminal_lock` — asserts ERR_TICKET_NOT_CALLED for calling a CANCELLED ticket, but PRD §3.3 names that error only for no-show/seating transitions, not the call transition. Not uniquely derivable.
- `Corner/state_machines/open_already_open_salon_rejected_invalid_from` — asserts ERR_STALE_SALON_VERSION on re-opening, contradicting PRD §2.9 ("seating is the sole optimistic-concurrency-controlled write"). A PRD-only implementer would not return that error on open.

Verified: all files py_compile clean; every PRD citation passes verbatim grep; no skip/xfail; computed expected values recomputed against PRD §3.5–§3.8.

## Step 6: Generate Implementation — 2026-06-23T18:07:50.000Z

NOTE: The concurrent Step 6 subagent hit a mid-response connection error. Investigation found it had actually written a COMPLETE app.py (1223 lines) plus all supporting modules to disk before the connection dropped; only the success report was lost. A follow-up synchronous completion agent recovered/verified rather than rewriting (the harness's unread-file guard preserved the complete recovered app.py). The original background agent also later reported completion — both converged on the same complete app.py.

Built complete Python + Flask implementation in workspace/implementation/:
- start.sh — foreground launcher; reads $PORT (default 10000), binds 0.0.0.0, guards pip install on `import flask`, `exec python3 app.py`.
- requirements.txt — flask==3.0.3
- app.py — 1223 lines, all 53 routes, error handlers, auth gate
- errors.py — ApiError + full error→HTTP catalogue (PRD §5)
- clock.py — server logical clock (defaults 2026-01-01T00:00:00Z, never wall-clock), ISO 8601 3-frac-digit
- db.py — in-memory Store (dicts keyed by id), created_at/updated_at/version stamping, monotonic seq tie-break
- response.py — meta/response_type/data envelope, datetime serialization, pagination meta
- middleware.py — X-User-ID/X-User-Role extraction + role check
- helpers.py — body/field validation (422), pagination (limit 10/min1/max100, offset 0), existence lookups
- domain.py — derived-field recompute (license_status, active_occupancy, loyalty_balance, no_show_strikes, queue position), settlement constants, calculations

**Endpoints: 53/53** — Flask url_map registers exactly 53 routes, matching PRD §4 1:1. No PRD gaps.

**Verification (all pass):** `python3 -c "import app"` → IMPORT_OK (verified on final disk state, 53 routes); boot smoke (PORT=8791) binds 0.0.0.0 foreground, 401 envelope w/o auth, 200 w/ auth, clock reads 2026-01-01T00:00:00.000Z; `bash start.sh` (PORT=8792) launches + serves; end-to-end lifecycle (salon→open→item/chair/tech/member→queue→call→seat→complete→settle) estimate=2000¢ final=2000¢ loyalty_earned=100 balance=100 all correct per §3.4/§3.6/§3.7. Storage in-memory only, no startup seeding.

## Step 7: Run Tests and Iterate — 2026-06-23T19:38:46.000Z

All 8 parallel rounds pass cleanly at 72/72 (failed=0, errors=0 every round). Loop complete.

**Iterations run:** 2 sweep-equivalent cycles (an initial diagnostic round that exposed a runner-invocation issue, then the fix round whose 8-round parallel sweep passed clean).

**Critical first finding (not a test/impl bug):** initial runs used `--start-command "bash start.sh"` without the mandatory `cd <impl> &&` prefix. Under per-test-server isolation the runner restarts the server from the pytest process's cwd (test_suite/), where start.sh does not exist, so every test errored "could not be restarted." Using `--start-command "cd <impl> && bash start.sh"` fixed all 73 boot errors and surfaced 7 real failures.

**Tests deleted (1):**
- `test_chair_not_sanitized_fires_when_license_valid` (test_03_seating_and_resources.py) — ERROR PRECEDENCE / not-uniquely-derivable. PRD §3.4 orders the seating chair gates OPEN-first; its setup builds a SANITIZING (not-OPEN) chair, which fails the OPEN gate first → ERR_CHAIR_NOT_OPEN (exactly what the kept companion test asserts). Given OPEN-first precedence + forward-only clock + mark-sanitized requiring clock≥ready, no PRD-faithful state ever reaches ERR_CHAIR_NOT_SANITIZED at seating; the assertion contradicted PRD's own precedence.

**Fixes applied to test_helpers/ (1 file):**
- `assertions.py` — added `same_instant()` (parses two ISO 8601 strings, compares UTC instant). The two `sanitation_ready_at` assertions in test_03 used literal-string `== "…10:05:00Z"`, but PRD §2.4 renders instants with three fractional digits, so the server value is `…10:05:00.000Z`. PRD §3.9 fixes the instant (end + sanitation_minutes), not a fractional-digit-free rendering; assertions now compare by instant, keeping the substantive check while dropping the over-specified format.

**Fixes applied to implementation/ (1 file, app.py):**
- `_finalize_settlement` (loyalty earn) — changed `((final_total // 100) * earn_rate) // 100` to `(final_total * earn_rate) // 10000`. PRD §3.6 specifies a single floor over the whole expression; the old code added an extra intermediate floor on the cents→dollars step (yielded 295 instead of 298 for final 5975).
- `void_visit` (retail stock conservation) — void restored RETAIL stock only in the SETTLED branch; for an unsettled (IN_SERVICE) void it voided lines without restoring stock. Per PRD §2.10 ("a void … must leave … the retail stock … exactly as they stood before the visit existed") and §3.8 ("leaves no residue in … inventory"), stock restoration moved into the single "void all ACTIVE lines" loop so every voided RETAIL line restores its quantity regardless of payment status.

**Final sweep:** all 8 parallel rounds passed 72/72 (failed=0, errors=0), zero union failures. Test total: 72 (73 original − 1 deleted).

## Step 8: Finalize PRD — 2026-06-23T19:42:38.000Z

PRD_FINALIZED.md produced (Step 7 had fixes → not skipped). Inline edits only.

**Line counts:** PRD.md = 292 lines, PRD_FINALIZED.md = 292 lines (0 line delta — all edits inline). Char delta: 42,914 → 44,234 (+1,320, +3.08%).

**Changes:**
- §2.4 — insert — instant-field rendering format: every instant-valued field (non-null) renders as three-fractional-digit ISO 8601 UTC `YYYY-MM-DDTHH:MM:SS.sssZ` (updated_at/license_expiry/sanitation_cert_expiry/sanitation_ready_at/joined_at/seated_at/ended_at); nulls render as JSON null — response.py:18-23 + clock.py:47-52.
- §3.6 — revise — loyalty-earn single floor: `floor(final_total_cents * earn_rate_bps / 10000)`, no independent floor on cents→dollars step (5975 @ 500 → 298, not 295) — app.py:1108.
- §3.8 — revise — void stock restoration regardless of payment status: retail stock_qty restoration moved out of SETTLED-only branch into the "every ACTIVE line → VOIDED" step; already-VOIDED lines not re-restored — app.py:1212-1220.

**Item not patched:** deleted test_chair_not_sanitized_fires_when_license_valid is a pure fixture/precedence bug — PRD §3.4 already uniquely orders seating gates OPEN-first (ERR_CHAIR_NOT_OPEN before ERR_CHAIR_NOT_SANITIZED), matching app.py:810-815. No edit.

Note: Step 8 agent observed test_suite/test_helpers/ live at task-dir level (not under workspace/); it aligned PRD_FINALIZED.md to implementation/ (the authoritative target) per spec.

## Step 9: Complete PRD — 2026-06-23T19:49:04.000Z

PRD_COMPLETED.md produced via full PRD-vs-implementation/ scan (always runs). Inline edits only.

**Source vs output:** PRD_FINALIZED.md (292 lines, 44,234 chars) → PRD_COMPLETED.md (292 lines, 46,243 chars). Char delta +2,009. Line count unchanged (every paragraph is a single physical line; all changes in-paragraph).

**Counts:** 8 changes — 6 ambiguity-pins, 2 mismatch-revisions.

**Per-change:**
- §3.1 (Members) — insert — ambiguity — no strike-expiry: every NO_SHOW counts as one un-expired strike, strikes never decay, SUSPENDED never auto-returns to ACTIVE — domain.py:53-66,69-82.
- §3.3 (call ticket) — insert — ambiguity — calling a non-WAITING ticket → ERR_TICKET_NOT_CALLED — app.py:712-713.
- §3.3 (cancel ticket) — insert — ambiguity — cancelling a ticket neither WAITING nor CALLED → ERR_TICKET_NOT_CALLED — app.py:767-768.
- §3.4 (seating) — insert — ambiguity — at-creation visit field values: ended_at null, used_package_credit false, final_total_cents and loyalty_earned 0 until completion — app.py:836-840.
- §3.5 (line void) — insert — ambiguity — voiding an already-VOIDED line → ERR_VISIT_NOT_IN_SERVICE (no dedicated code) — app.py:998-1000.
- §3.6 (package activate/cancel) — insert — mismatch — no PENDING→ACTIVE / state-machine guard; activate unconditionally sets ACTIVE + re-stamps/replenishes tier fields, cancel unconditionally sets CANCELLED — app.py:450-468,471-480.
- §3.6 (settlement discount) — revise — mismatch — discount applies when status is ACTIVE or DEPLETED (package depleted by this visit's own draw, or earlier, still confers tier discount; only PENDING/CANCELLED confer none) — app.py:1089,1115-1123.
- §3.7 (loyalty adjustment) — insert — ambiguity — points is a required signed integer (may be negative); returns 201 Created with the created LoyaltyLedgerEntry as data, not the member — app.py:335-344.
- §3.9 (mark-sanitized) — insert — ambiguity — only gate is the window check (when sanitation_ready_at non-null); null-sanitation_ready_at chair set OPEN unconditionally; call does not clear sanitation_ready_at — app.py:240-250.

Confirmed already-pinned (no change): seating validation precedence (§3.4); salon-version increment points (§2.9, all five touch(salon) sites); per-step floored loyalty/discount math (§2.8/§3.6); open/close ignoring body version field (§2.9); list-role authorizations (§4); never-reachable RETIRED/OFF_SHIFT states (no transition endpoint).

---

## PIPELINE COMPLETE — 2026-06-23T19:49:04.000Z

All Steps 1–9 finished in a single continuous run. Terminal artifact workspace/PRD_COMPLETED.md exists on disk (46,243 bytes). Final test state: 8/8 parallel rounds passing at 72/72. Implementation: 53 routes, in-memory storage, boots cleanly via start.sh.
