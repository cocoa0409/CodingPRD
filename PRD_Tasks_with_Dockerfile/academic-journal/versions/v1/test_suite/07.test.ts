import {
  apiClient,
  buildUserHeaders,
  handleApiResponse,
  validateErrorEnvelope, createReviewAssignmentPayload, createReviewInvitationPayload,
  Journal, ReviewAssignment, Review,
  ManuscriptStatus,
  ReviewStatus,
  UserRole,
  ApiErrorId, setupJournal,
  setupJournalInReview,
  setupInvitedReview,
  setupManuscript,
  setupReviewerProfile
} from '../../../test-helpers';

describe('Phase 4: Edge Cases and Complex Scenarios', () => {
  const journalEditorHeaders = buildUserHeaders('jour-editor-1', UserRole.JournalEditor);
  const sectionEditorHeaders = buildUserHeaders('sect-editor-1', UserRole.SectionEditor);
  const managingEditorHeaders = buildUserHeaders('mng-editor-1', UserRole.ManagingEditor);

  it('should default required_anonymity_level to DOUBLE_BLIND when omitted', async () => {
    const journal = await setupJournal();
    const manuscript = await setupManuscript(journal.id);

    const inReviewRes = await apiClient.beginReview(journal.id, journalEditorHeaders);
    const inReviewJournal = handleApiResponse<Journal>(inReviewRes, 200);

    await apiClient.updateManuscript(inReviewJournal.id, manuscript.id, { status: ManuscriptStatus.PENDING_REVIEW }, journalEditorHeaders);

    const assignmentPayload = createReviewAssignmentPayload();
    delete (assignmentPayload as Partial<typeof assignmentPayload>).required_anonymity_level;

    const assignmentRes = await apiClient.createReviewAssignment(inReviewJournal.id, manuscript.id, assignmentPayload, sectionEditorHeaders);
    const assignment = handleApiResponse<ReviewAssignment>(assignmentRes, 201);

    expect(assignment.required_anonymity_level).toBe('DOUBLE_BLIND');
  });

  it('should not increase risk score if a review is not in an extra revision cycle', async () => {
    const { journal, review } = await setupInvitedReview();

    expect(review.in_extra_revision_cycle).toBe(false);
    const journalState1 = await apiClient.getJournal(journal.id, journalEditorHeaders).then(res => handleApiResponse<Journal>(res, 200));
    expect(journalState1.desk_reject_risk_score).toBe(0);

    await apiClient.cancelReview(journal.id, review.id, journalEditorHeaders);

    const journalState2 = await apiClient.getJournal(journal.id, journalEditorHeaders).then(res => handleApiResponse<Journal>(res, 200));
    expect(journalState2.desk_reject_risk_score).toBe(0);
  });

  describe('Review mutations are journal-isolated', () => {
    let journalA: Journal;
    let journalB: Journal;
    let reviewInA: Review;

    beforeEach(async () => {
      const { journal: jA, review: rA } = await setupInvitedReview();
      journalA = jA;
      reviewInA = rA;
      journalB = await setupJournalInReview();
    });

    it('should fail to CANCEL a review via the wrong journal path', async () => {
      const cancelRes = await apiClient.cancelReview(journalB.id, reviewInA.id, journalEditorHeaders);
      validateErrorEnvelope(cancelRes, { expectedErrorId: ApiErrorId.ERR_REVIEW_NOT_FOUND });
    });
  });

  it('should calculate and record final_prestige_cost upon publication finalization', async () => {
    const journal = await setupJournal({ total_prestige: 100 });
    const manuscript = await setupManuscript(journal.id);
    const reviewer = await setupReviewerProfile(journal.id);

    const inReviewRes = await apiClient.beginReview(journal.id, journalEditorHeaders);
    const inReviewJournal = handleApiResponse<Journal>(inReviewRes, 200);

    const firstAssignment = await apiClient.createReviewAssignment(inReviewJournal.id, manuscript.id, createReviewAssignmentPayload(), sectionEditorHeaders).then(res => handleApiResponse<ReviewAssignment>(res, 201));
    await apiClient.updateManuscript(inReviewJournal.id, manuscript.id, { status: ManuscriptStatus.PENDING_REVIEW }, journalEditorHeaders);

    const firstReview = await apiClient.inviteReviewer(inReviewJournal.id, createReviewInvitationPayload(firstAssignment.id, reviewer.id), sectionEditorHeaders).then(res => handleApiResponse<Review>(res, 201));
    await apiClient.acceptReview(inReviewJournal.id, firstReview.id, journalEditorHeaders);
    await apiClient.submitReview(inReviewJournal.id, firstReview.id, journalEditorHeaders);

    for (let i = 1; i < 3; i++) {
      const assignment = await apiClient.createReviewAssignment(inReviewJournal.id, manuscript.id, createReviewAssignmentPayload(), sectionEditorHeaders).then(res => handleApiResponse<ReviewAssignment>(res, 201));
      const review = await apiClient.inviteReviewer(inReviewJournal.id, createReviewInvitationPayload(assignment.id, reviewer.id), sectionEditorHeaders).then(res => handleApiResponse<Review>(res, 201));
      await apiClient.acceptReview(inReviewJournal.id, review.id, journalEditorHeaders);
      await apiClient.submitReview(inReviewJournal.id, review.id, journalEditorHeaders);
    }

    const assignment4 = await apiClient.createReviewAssignment(inReviewJournal.id, manuscript.id, createReviewAssignmentPayload(), sectionEditorHeaders).then(res => handleApiResponse<ReviewAssignment>(res, 201));
    const review4 = await apiClient.inviteReviewer(inReviewJournal.id, createReviewInvitationPayload(assignment4.id, reviewer.id), sectionEditorHeaders).then(res => handleApiResponse<Review>(res, 201));

    expect(review4.in_extra_revision_cycle).toBe(true);
    expect(review4.provisional_prestige_cost).toBe(1 * 1.5);

    await apiClient.acceptReview(inReviewJournal.id, review4.id, journalEditorHeaders);
    await apiClient.submitReview(inReviewJournal.id, review4.id, journalEditorHeaders);

    const beforeFinalization = await apiClient.getReview(inReviewJournal.id, review4.id, journalEditorHeaders).then(res => handleApiResponse<Review>(res, 200));
    expect(beforeFinalization.status).toBe(ReviewStatus.SUBMITTED);
    expect(beforeFinalization.final_prestige_cost).toBeNull();

    await apiClient.initiatePublication(inReviewJournal.id, journalEditorHeaders);
    await apiClient.finalizePublication(inReviewJournal.id, managingEditorHeaders);

    const finalReview = await apiClient.getReview(inReviewJournal.id, review4.id, journalEditorHeaders).then(res => handleApiResponse<Review>(res, 200));
    expect(finalReview.status).toBe(ReviewStatus.PUBLISHED);
    expect(finalReview.final_prestige_cost).not.toBeNull();
    expect(typeof finalReview.final_prestige_cost).toBe('number');
    expect(finalReview.final_prestige_cost).toBe(1.5);

    const finalStandardReview = await apiClient.getReview(inReviewJournal.id, firstReview.id, journalEditorHeaders).then(res => handleApiResponse<Review>(res, 200));
    expect(finalStandardReview.status).toBe(ReviewStatus.PUBLISHED);
    expect(finalStandardReview.final_prestige_cost).toBe(1);
  });

  it('should correctly calculate provisional prestige cost for extra revision cycle', async () => {
    const journal = await setupJournal({ total_prestige: 50 });
    const manuscript = await setupManuscript(journal.id);
    const reviewer = await setupReviewerProfile(journal.id);

    const inReviewRes = await apiClient.beginReview(journal.id, journalEditorHeaders);
    const inReviewJournal = handleApiResponse<Journal>(inReviewRes, 200);

    const firstAssignment = await apiClient.createReviewAssignment(inReviewJournal.id, manuscript.id, createReviewAssignmentPayload(), sectionEditorHeaders).then(res => handleApiResponse<ReviewAssignment>(res, 201));

    await apiClient.updateManuscript(inReviewJournal.id, manuscript.id, { status: ManuscriptStatus.PENDING_REVIEW }, journalEditorHeaders);

    const firstReview = await apiClient.inviteReviewer(inReviewJournal.id, createReviewInvitationPayload(firstAssignment.id, reviewer.id), sectionEditorHeaders).then(res => handleApiResponse<Review>(res, 201));
    await apiClient.acceptReview(inReviewJournal.id, firstReview.id, journalEditorHeaders);

    for (let i = 1; i < 3; i++) {
      const assignment = await apiClient.createReviewAssignment(inReviewJournal.id, manuscript.id, createReviewAssignmentPayload(), sectionEditorHeaders).then(res => handleApiResponse<ReviewAssignment>(res, 201));
      const review = await apiClient.inviteReviewer(inReviewJournal.id, createReviewInvitationPayload(assignment.id, reviewer.id), sectionEditorHeaders).then(res => handleApiResponse<Review>(res, 201));
      await apiClient.acceptReview(inReviewJournal.id, review.id, journalEditorHeaders);
    }

    const journalAfterBase = await apiClient.getJournal(inReviewJournal.id, journalEditorHeaders).then(res => handleApiResponse<Journal>(res, 200));
    expect(journalAfterBase.prestige_balance).toBe(50 - 10 - 3);

    const extraAssignment = await apiClient.createReviewAssignment(inReviewJournal.id, manuscript.id, createReviewAssignmentPayload(), sectionEditorHeaders).then(res => handleApiResponse<ReviewAssignment>(res, 201));
    const extraReviewRes = await apiClient.inviteReviewer(inReviewJournal.id, createReviewInvitationPayload(extraAssignment.id, reviewer.id), sectionEditorHeaders);
    const extraReview = handleApiResponse<Review>(extraReviewRes, 201);

    const expectedProvisionalCost = 1 * 1.5;
    expect(extraReview.in_extra_revision_cycle).toBe(true);
    expect(extraReview.provisional_prestige_cost).toBe(expectedProvisionalCost);

    await apiClient.acceptReview(inReviewJournal.id, extraReview.id, journalEditorHeaders);
    const journalAfterExtra = await apiClient.getJournal(inReviewJournal.id, journalEditorHeaders).then(res => handleApiResponse<Journal>(res, 200));
    const expectedPrestige = 50 - 10 - 3 - expectedProvisionalCost;
    expect(journalAfterExtra.prestige_balance).toBeCloseTo(expectedPrestige);
  });

  it('should correctly credit prestige on decline and prevent multiple declines', async () => {
    const { journal, review } = await setupInvitedReview({
      isExtraRevision: true,
      journalPrestige: 100,
    });
    const cost = review.provisional_prestige_cost;

    const journalState1 = await apiClient.getJournal(journal.id, journalEditorHeaders).then(res => handleApiResponse<Journal>(res, 200));
    const initialPrestige = journalState1.total_prestige;
    const expectedRisk = review.in_extra_revision_cycle ? 20 : 0;
    expect(journalState1.desk_reject_risk_score).toBe(expectedRisk);
    expect(journalState1.prestige_balance).toBe(initialPrestige - 10 - cost);

    await apiClient.declineReview(journal.id, review.id, journalEditorHeaders);
    const journalState2 = await apiClient.getJournal(journal.id, journalEditorHeaders).then(res => handleApiResponse<Journal>(res, 200));
    expect(journalState2.prestige_balance).toBe(initialPrestige - 10);
    expect(journalState2.desk_reject_risk_score).toBe(0);

    const declineAgainRes = await apiClient.declineReview(journal.id, review.id, journalEditorHeaders);
    validateErrorEnvelope(declineAgainRes, { expectedErrorId: ApiErrorId.ERR_REVIEW_LIFECYCLE_STATE_INVALID });

    const finalJournalState = await apiClient.getJournal(journal.id, journalEditorHeaders).then(res => handleApiResponse<Journal>(res, 200));
    expect(finalJournalState.prestige_balance).toBe(initialPrestige - 10);
    expect(finalJournalState.desk_reject_risk_score).toBe(0);
  });

  it('should succeed when review cost exactly matches remaining prestige', async () => {
    const journal = await setupJournal({ total_prestige: 11 });
    const manuscript = await setupManuscript(journal.id);
    const reviewer = await setupReviewerProfile(journal.id);

    const inReviewRes = await apiClient.beginReview(journal.id, journalEditorHeaders);
    const inReviewJournal = handleApiResponse<Journal>(inReviewRes, 200);

    const assignment = await apiClient.createReviewAssignment(inReviewJournal.id, manuscript.id, createReviewAssignmentPayload(), sectionEditorHeaders).then(res => handleApiResponse<ReviewAssignment>(res, 201));
    await apiClient.updateManuscript(inReviewJournal.id, manuscript.id, { status: ManuscriptStatus.PENDING_REVIEW }, journalEditorHeaders);

    const reviewRes = await apiClient.inviteReviewer(inReviewJournal.id, createReviewInvitationPayload(assignment.id, reviewer.id), sectionEditorHeaders);
    expect(reviewRes.status).toBe(201);
    const review = handleApiResponse<Review>(reviewRes, 201);

    expect(review.provisional_prestige_cost).toBeCloseTo(1);
    const journalCheck = await apiClient.getJournal(inReviewJournal.id, journalEditorHeaders).then(res => handleApiResponse<Journal>(res, 200));
    expect(journalCheck.prestige_balance).toBeCloseTo(0);
  });

  it('should fail when review cost exceeds prestige by one cent (or smallest unit)', async () => {
    const journal = await setupJournal({ total_prestige: 10 });
    const manuscript = await setupManuscript(journal.id);
    const reviewer = await setupReviewerProfile(journal.id);

    const inReviewRes = await apiClient.beginReview(journal.id, journalEditorHeaders);
    const inReviewJournal = handleApiResponse<Journal>(inReviewRes, 200);

    const assignment = await apiClient.createReviewAssignment(inReviewJournal.id, manuscript.id, createReviewAssignmentPayload(), sectionEditorHeaders).then(res => handleApiResponse<ReviewAssignment>(res, 201));
    await apiClient.updateManuscript(inReviewJournal.id, manuscript.id, { status: ManuscriptStatus.PENDING_REVIEW }, journalEditorHeaders);

    const reviewRes = await apiClient.inviteReviewer(inReviewJournal.id, createReviewInvitationPayload(assignment.id, reviewer.id), sectionEditorHeaders);
    validateErrorEnvelope(reviewRes, { expectedErrorId: ApiErrorId.ERR_INSUFFICIENT_PRESTIGE });
  });

  it('should fail if cost exceeds prestige due to extra revision penalty', async () => {
    const journal = await setupJournal({ total_prestige: 14 });
    const manuscript = await setupManuscript(journal.id);
    const reviewer = await setupReviewerProfile(journal.id);

    const inReviewRes = await apiClient.beginReview(journal.id, journalEditorHeaders);
    const inReviewJournal = handleApiResponse<Journal>(inReviewRes, 200);

    const firstAssignment = await apiClient.createReviewAssignment(inReviewJournal.id, manuscript.id, createReviewAssignmentPayload(), sectionEditorHeaders).then(res => handleApiResponse<ReviewAssignment>(res, 201));
    await apiClient.updateManuscript(inReviewJournal.id, manuscript.id, { status: ManuscriptStatus.PENDING_REVIEW }, journalEditorHeaders);

    const firstReview = await apiClient.inviteReviewer(inReviewJournal.id, createReviewInvitationPayload(firstAssignment.id, reviewer.id), sectionEditorHeaders).then(res => handleApiResponse<Review>(res, 201));
    await apiClient.acceptReview(inReviewJournal.id, firstReview.id, journalEditorHeaders);

    for (let i = 1; i < 3; i++) {
      const assignment = await apiClient.createReviewAssignment(inReviewJournal.id, manuscript.id, createReviewAssignmentPayload(), sectionEditorHeaders).then(res => handleApiResponse<ReviewAssignment>(res, 201));
      const review = await apiClient.inviteReviewer(inReviewJournal.id, createReviewInvitationPayload(assignment.id, reviewer.id), sectionEditorHeaders).then(res => handleApiResponse<Review>(res, 201));
      await apiClient.acceptReview(inReviewJournal.id, review.id, journalEditorHeaders);
    }

    const extraAssignment = await apiClient.createReviewAssignment(inReviewJournal.id, manuscript.id, createReviewAssignmentPayload(), sectionEditorHeaders).then(res => handleApiResponse<ReviewAssignment>(res, 201));
    const extraReviewRes = await apiClient.inviteReviewer(inReviewJournal.id, createReviewInvitationPayload(extraAssignment.id, reviewer.id), sectionEditorHeaders);

    validateErrorEnvelope(extraReviewRes, { expectedErrorId: ApiErrorId.ERR_INSUFFICIENT_PRESTIGE });
    const journalCheck = await apiClient.getJournal(inReviewJournal.id, journalEditorHeaders).then(res => handleApiResponse<Journal>(res, 200));
    expect(journalCheck.prestige_balance).toBeCloseTo(1);
    expect(journalCheck.desk_reject_risk_score).toBe(0);
  });

  it('should allow new review after prestige is freed by decline', async () => {
    const journal = await setupJournal({ total_prestige: 11 });
    const manuscript = await setupManuscript(journal.id);
    const reviewer = await setupReviewerProfile(journal.id);

    const inReviewRes = await apiClient.beginReview(journal.id, journalEditorHeaders);
    const inReviewJournal = handleApiResponse<Journal>(inReviewRes, 200);

    const assignmentA = await apiClient.createReviewAssignment(inReviewJournal.id, manuscript.id, createReviewAssignmentPayload(), sectionEditorHeaders).then(res => handleApiResponse<ReviewAssignment>(res, 201));
    await apiClient.updateManuscript(inReviewJournal.id, manuscript.id, { status: ManuscriptStatus.PENDING_REVIEW }, journalEditorHeaders);
    const reviewA = await apiClient.inviteReviewer(inReviewJournal.id, createReviewInvitationPayload(assignmentA.id, reviewer.id), sectionEditorHeaders).then(res => handleApiResponse<Review>(res, 201));

    const assignmentB = await apiClient.createReviewAssignment(inReviewJournal.id, manuscript.id, createReviewAssignmentPayload(), sectionEditorHeaders).then(res => handleApiResponse<ReviewAssignment>(res, 201));

    await apiClient.declineReview(inReviewJournal.id, reviewA.id, journalEditorHeaders);

    const reviewBRes = await apiClient.inviteReviewer(inReviewJournal.id, createReviewInvitationPayload(assignmentB.id, reviewer.id), sectionEditorHeaders);
    expect(reviewBRes.status).toBe(201);
    const reviewB = handleApiResponse<Review>(reviewBRes, 201);

    expect(reviewB.provisional_prestige_cost).toBeCloseTo(1);
    const journalCheck = await apiClient.getJournal(inReviewJournal.id, journalEditorHeaders).then(res => handleApiResponse<Journal>(res, 200));
    expect(journalCheck.prestige_balance).toBeCloseTo(0);
  });

  it('should correctly deduct initial submission cost when transitioning to PENDING_REVIEW', async () => {
    const journal = await setupJournal({ total_prestige: 50 });
    const manuscript = await setupManuscript(journal.id);

    const inReviewRes = await apiClient.beginReview(journal.id, journalEditorHeaders);
    const inReviewJournal = handleApiResponse<Journal>(inReviewRes, 200);

    const journalBefore = await apiClient.getJournal(inReviewJournal.id, journalEditorHeaders).then(res => handleApiResponse<Journal>(res, 200));
    expect(journalBefore.prestige_balance).toBe(50);

    await apiClient.createReviewAssignment(inReviewJournal.id, manuscript.id, createReviewAssignmentPayload(), sectionEditorHeaders);

    await apiClient.updateManuscript(inReviewJournal.id, manuscript.id, { status: ManuscriptStatus.PENDING_REVIEW }, journalEditorHeaders);

    const journalAfter = await apiClient.getJournal(inReviewJournal.id, journalEditorHeaders).then(res => handleApiResponse<Journal>(res, 200));
    expect(journalAfter.prestige_balance).toBe(40);
  });

  it('should correctly handle prestige for multiple manuscripts', async () => {
    const journal = await setupJournal({ total_prestige: 100 });
    const manuscript1 = await setupManuscript(journal.id);
    const manuscript2 = await setupManuscript(journal.id);
    const reviewer = await setupReviewerProfile(journal.id);

    const inReviewRes = await apiClient.beginReview(journal.id, journalEditorHeaders);
    const inReviewJournal = handleApiResponse<Journal>(inReviewRes, 200);

    const assignment1 = await apiClient.createReviewAssignment(inReviewJournal.id, manuscript1.id, createReviewAssignmentPayload(), sectionEditorHeaders).then(res => handleApiResponse<ReviewAssignment>(res, 201));
    await apiClient.updateManuscript(inReviewJournal.id, manuscript1.id, { status: ManuscriptStatus.PENDING_REVIEW }, journalEditorHeaders);
    await apiClient.inviteReviewer(inReviewJournal.id, createReviewInvitationPayload(assignment1.id, reviewer.id), sectionEditorHeaders);

    const assignment2 = await apiClient.createReviewAssignment(inReviewJournal.id, manuscript2.id, createReviewAssignmentPayload(), sectionEditorHeaders).then(res => handleApiResponse<ReviewAssignment>(res, 201));
    await apiClient.updateManuscript(inReviewJournal.id, manuscript2.id, { status: ManuscriptStatus.PENDING_REVIEW }, journalEditorHeaders);
    await apiClient.inviteReviewer(inReviewJournal.id, createReviewInvitationPayload(assignment2.id, reviewer.id), sectionEditorHeaders);

    const journalAfter2 = await apiClient.getJournal(inReviewJournal.id, journalEditorHeaders).then(res => handleApiResponse<Journal>(res, 200));
    expect(journalAfter2.prestige_balance).toBe(100 - 10 - 1 - 10 - 1);
  });
});
