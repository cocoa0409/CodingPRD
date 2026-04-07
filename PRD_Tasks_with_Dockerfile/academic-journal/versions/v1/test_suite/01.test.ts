import {
  apiClient,
  ApiHeadersBase,
  buildUserHeaders,
  handleApiResponse,
  validateApiResponseStructure,
  validateErrorEnvelope,
  assertJournal,
  assertManuscript, assertReviewerProfile, assertConflictOfInterest,
  assertCertification,
  createJournalPayload,
  createManuscriptPayload,
  createReviewAssignmentPayload,
  createReviewerProfilePayload,
  createReviewInvitationPayload,
  createConflictOfInterestPayload,
  createCertificationPayload,
  Journal,
  Manuscript,
  ReviewAssignment,
  ReviewerProfile,
  Review,
  ConflictOfInterest,
  Certification,
  JournalStatus,
  ManuscriptStatus,
  UserRole,
  ConflictOfInterestType,
  CertificationName,
  ApiErrorId,
  setupJournal,
  setupJournalInReview
} from '../../../test-helpers';

describe('Phase 1: Endpoint Validation', () => {
  const journalEditorHeaders = buildUserHeaders('je-1', UserRole.JournalEditor);
  const sectionEditorHeaders = buildUserHeaders('se-1', UserRole.SectionEditor);
  const managingEditorHeaders = buildUserHeaders('me-1', UserRole.ManagingEditor);

  const NON_EXISTENT_UUID = '00000000-0000-0000-0000-000000000000';

  async function fetchAllJournals(headers: ApiHeadersBase): Promise<Journal[]> {
    let offset = 0;
    const all: Journal[] = [];
    while (true) {
      const res = await apiClient.getJournals(headers, { limit: 100, offset });
      const envelope = validateApiResponseStructure<Journal[]>(res, { expectPaginated: true });
      all.push(...envelope.data);
      if (!envelope.meta.has_more) break;
      offset += envelope.meta.limit ?? 0;
    }
    return all;
  }

  describe('Journal Resource', () => {
    it('should create a new Journal', async () => {
      const payload = createJournalPayload({
        journal_name: 'Journal of Computational Biology 2025',
        total_prestige: 1000,
      });

      const res = await apiClient.createJournal(payload, journalEditorHeaders);
      const journal = handleApiResponse<Journal>(res, 201);

      assertJournal(journal);

      expect(journal.journal_name).toBe('Journal of Computational Biology 2025');
      expect(journal.total_prestige).toBe(1000);
      expect(journal.status).toBe(JournalStatus.ACCEPTING_SUBMISSIONS);
      expect(journal.prestige_balance).toBe(1000);
      expect(journal.desk_reject_risk_score).toBe(0);
    });

    it('should list all Journals in ascending order of creation', async () => {
      const journal1Payload = createJournalPayload({ journal_name: 'Journal 1' });
      const journal2Payload = createJournalPayload({ journal_name: 'Journal 2' });

      const res1 = await apiClient.createJournal(journal1Payload, journalEditorHeaders);
      const journal1 = handleApiResponse<Journal>(res1, 201);
      await new Promise(resolve => setTimeout(resolve, 10));
      const res2 = await apiClient.createJournal(journal2Payload, journalEditorHeaders);
      const journal2 = handleApiResponse<Journal>(res2, 201);

      const journals = await fetchAllJournals(journalEditorHeaders);

      expect(journals.length).toBeGreaterThanOrEqual(2);
      const journalIds = journals.map(j => j.id);
      expect(journalIds).toContain(journal1.id);
      expect(journalIds).toContain(journal2.id);

      const journal1Index = journals.findIndex(j => j.id === journal1.id);
      const journal2Index = journals.findIndex(j => j.id === journal2.id);
      expect(journal1Index).toBeLessThan(journal2Index);
    });

    describe('Pagination for Journals', () => {
      beforeEach(async () => {
        await apiClient.createJournal(createJournalPayload({ journal_name: 'PagiJournal 1' }), journalEditorHeaders);
        await apiClient.createJournal(createJournalPayload({ journal_name: 'PagiJournal 2' }), journalEditorHeaders);
        await apiClient.createJournal(createJournalPayload({ journal_name: 'PagiJournal 3' }), journalEditorHeaders);
      });

      it('should respect the limit parameter', async () => {
        const listRes = await apiClient.getJournals(journalEditorHeaders, { limit: 2 });
        const journals = handleApiResponse<Journal[]>(listRes, 200, { expectPaginated: true });
        expect(journals.length).toBe(2);
      });

      it('should respect the offset parameter', async () => {
        const fullListRes = await apiClient.getJournals(journalEditorHeaders, { limit: 100 });
        const fullList = handleApiResponse<Journal[]>(fullListRes, 200, { expectPaginated: true });
        const secondJournalId = fullList[1].id;

        const listRes = await apiClient.getJournals(journalEditorHeaders, { limit: 1, offset: 1 });
        const journals = handleApiResponse<Journal[]>(listRes, 200, { expectPaginated: true });

        expect(journals.length).toBe(1);
        expect(journals[0].id).toBe(secondJournalId);
      });
    });
  });

  describe('Manuscript Resource', () => {
    let testJournal: Journal;

    beforeEach(async () => {
      const journalRes = await apiClient.createJournal(
        createJournalPayload({ journal_name: 'Manuscript Test Journal' }),
        journalEditorHeaders
      );
      testJournal = handleApiResponse<Journal>(journalRes, 201);
    });

    it('should create a Manuscript under an existing Journal without risk penalty for normal submission', async () => {

      const journalBeforeRes = await apiClient.getJournal(testJournal.id, journalEditorHeaders);
      const journalBefore = handleApiResponse<Journal>(journalBeforeRes, 200);
      const initialRiskScore = journalBefore.desk_reject_risk_score;

      const payload = createManuscriptPayload({
        title: 'Novel Applications of Machine Learning',
        submission_date: 1672531200,
        is_fast_track_submission: false,
      });

      const res = await apiClient.createManuscript(testJournal.id, payload, sectionEditorHeaders);
      const manuscript = handleApiResponse<Manuscript>(res, 201);

      assertManuscript(manuscript);
      expect(manuscript.title).toBe('Novel Applications of Machine Learning');
      expect(manuscript.journal_id).toBe(testJournal.id);
      expect(manuscript.status).toBe(ManuscriptStatus.DRAFT);
      expect(manuscript.is_fast_track_submission).toBe(false);

      const journalAfterRes = await apiClient.getJournal(testJournal.id, journalEditorHeaders);
      const journalAfter = handleApiResponse<Journal>(journalAfterRes, 200);
      expect(journalAfter.desk_reject_risk_score).toBe(initialRiskScore);
    });

    it('should create a fast-track Manuscript and apply 5-point risk penalty to journal', async () => {

      const journalBeforeRes = await apiClient.getJournal(testJournal.id, journalEditorHeaders);
      const journalBefore = handleApiResponse<Journal>(journalBeforeRes, 200);
      const initialRiskScore = journalBefore.desk_reject_risk_score;

      const payload = createManuscriptPayload({
        title: 'Urgent Clinical Trial Results',
        submission_date: 1672531200,
        is_fast_track_submission: true,
      });

      const res = await apiClient.createManuscript(testJournal.id, payload, sectionEditorHeaders);
      const manuscript = handleApiResponse<Manuscript>(res, 201);

      assertManuscript(manuscript);
      expect(manuscript.title).toBe('Urgent Clinical Trial Results');
      expect(manuscript.journal_id).toBe(testJournal.id);
      expect(manuscript.status).toBe(ManuscriptStatus.DRAFT);
      expect(manuscript.is_fast_track_submission).toBe(true);

      const journalAfterRes = await apiClient.getJournal(testJournal.id, journalEditorHeaders);
      const journalAfter = handleApiResponse<Journal>(journalAfterRes, 200);
      expect(journalAfter.desk_reject_risk_score).toBe(initialRiskScore + 5);
    });

    it('should not perform operations on a non-existent Journal', async () => {
      const payload = createManuscriptPayload();
      const res1 = await apiClient.createManuscript(NON_EXISTENT_UUID, payload, sectionEditorHeaders);
      validateErrorEnvelope(res1, { expectedErrorId: ApiErrorId.ERR_JOURNAL_NOT_FOUND });

      const res2 = await apiClient.getManuscripts(NON_EXISTENT_UUID, journalEditorHeaders);
      validateErrorEnvelope(res2, { expectedErrorId: ApiErrorId.ERR_JOURNAL_NOT_FOUND });

      const manuscriptRes = await apiClient.createManuscript(
        testJournal.id,
        createManuscriptPayload(),
        sectionEditorHeaders
      );
      const manuscript = handleApiResponse<Manuscript>(manuscriptRes, 201);

      const res3 = await apiClient.getManuscript(NON_EXISTENT_UUID, manuscript.id, journalEditorHeaders);
      validateErrorEnvelope(res3, { expectedErrorId: ApiErrorId.ERR_JOURNAL_NOT_FOUND });
    });

    describe('Pagination for Manuscripts', () => {
      beforeEach(async () => {
        await apiClient.createManuscript(testJournal.id, createManuscriptPayload({ title: 'Manuscript A' }), sectionEditorHeaders);
        await apiClient.createManuscript(testJournal.id, createManuscriptPayload({ title: 'Manuscript B' }), sectionEditorHeaders);
        await apiClient.createManuscript(testJournal.id, createManuscriptPayload({ title: 'Manuscript C' }), sectionEditorHeaders);
      });

      it('should respect the limit parameter for manuscripts', async () => {
        const listRes = await apiClient.getManuscripts(testJournal.id, journalEditorHeaders, { limit: 1 });
        const manuscripts = handleApiResponse<Manuscript[]>(listRes, 200, { expectPaginated: true });
        expect(manuscripts.length).toBe(1);
      });

      it('should accept requests with limit=100', async () => {
        const res = await apiClient.getManuscripts(testJournal.id, journalEditorHeaders, { limit: 100 });

        expect(res.status).toBe(200);
        const manuscripts = handleApiResponse<Manuscript[]>(res, 200, { expectPaginated: true });
        expect(manuscripts.length).toBeLessThanOrEqual(100);
      });

      it('should respect the offset parameter for manuscripts', async () => {
        const fullListRes = await apiClient.getManuscripts(testJournal.id, journalEditorHeaders);
        const fullList = handleApiResponse<Manuscript[]>(fullListRes, 200, { expectPaginated: true });
        const secondManuscriptId = fullList[1].id;

        const listRes = await apiClient.getManuscripts(testJournal.id, journalEditorHeaders, { limit: 1, offset: 1 });
        const manuscripts = handleApiResponse<Manuscript[]>(listRes, 200, { expectPaginated: true });

        expect(manuscripts.length).toBe(1);
        expect(manuscripts[0].id).toBe(secondManuscriptId);
      });
    });

    it('should not perform operations on a non-existent Manuscript', async () => {
      const res1 = await apiClient.getManuscript(testJournal.id, NON_EXISTENT_UUID, journalEditorHeaders);
      validateErrorEnvelope(res1, { expectedErrorId: ApiErrorId.ERR_MANUSCRIPT_NOT_FOUND });

      const res2 = await apiClient.updateManuscript(
        testJournal.id,
        NON_EXISTENT_UUID,
        { status: ManuscriptStatus.PENDING_REVIEW },
        journalEditorHeaders
      );
      validateErrorEnvelope(res2, { expectedErrorId: ApiErrorId.ERR_MANUSCRIPT_NOT_FOUND });
    });

    it('should handle data isolation for a Manuscript from a different journal', async () => {
      const journalA = await setupJournal({ journal_name: 'Journal A' });
      const journalB = await setupJournal({ journal_name: 'Journal B' });

      const manuscriptRes = await apiClient.createManuscript(
        journalB.id,
        createManuscriptPayload({ title: 'Journal B Manuscript' }),
        sectionEditorHeaders
      );
      const manuscriptB = handleApiResponse<Manuscript>(manuscriptRes, 201);

      const res = await apiClient.getManuscript(journalA.id, manuscriptB.id, journalEditorHeaders);
      validateErrorEnvelope(res, {
        expectedErrorId: ApiErrorId.ERR_MANUSCRIPT_NOT_FOUND,
      });
    });

    it('should handle data isolation when updating a Manuscript from different journal', async () => {
      const journalA = await setupJournal({ journal_name: 'Journal A' });
      const journalB = await setupJournal({ journal_name: 'Journal B' });

      const manuscriptRes = await apiClient.createManuscript(
        journalB.id,
        createManuscriptPayload(),
        sectionEditorHeaders
      );
      const manuscriptB = handleApiResponse<Manuscript>(manuscriptRes, 201);

      const res = await apiClient.updateManuscript(
        journalA.id,
        manuscriptB.id,
        { status: ManuscriptStatus.PENDING_REVIEW },
        journalEditorHeaders
      );
      validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_MANUSCRIPT_NOT_FOUND });
    });
  });

  describe('ReviewAssignment Resource', () => {
    let journal: Journal;
    let manuscript: Manuscript;

    beforeEach(async () => {
      const journalRes = await apiClient.createJournal(
        createJournalPayload({ journal_name: 'Assignment Test Journal' }),
        journalEditorHeaders
      );
      journal = handleApiResponse<Journal>(journalRes, 201);

      const manuscriptRes = await apiClient.createManuscript(
        journal.id,
        createManuscriptPayload({ title: 'Assignment Test Manuscript' }),
        sectionEditorHeaders
      );
      manuscript = handleApiResponse<Manuscript>(manuscriptRes, 201);

      await apiClient.beginReview(journal.id, journalEditorHeaders);
    });

    it('should not create an Assignment under a non-existent Manuscript', async () => {
      const assignmentPayload = createReviewAssignmentPayload();
      const res = await apiClient.createReviewAssignment(
        journal.id,
        NON_EXISTENT_UUID,
        assignmentPayload,
        sectionEditorHeaders
      );
      validateErrorEnvelope(res, {
        expectedErrorId: ApiErrorId.ERR_MANUSCRIPT_NOT_FOUND
      });
    });

    it('should not get a non-existent Assignment', async () => {
      const res = await apiClient.getReviewAssignment(
        journal.id,
        manuscript.id,
        NON_EXISTENT_UUID,
        journalEditorHeaders
      );
      validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_ASSIGNMENT_NOT_FOUND });
    });

    it('should handle data isolation when getting an assignment from the wrong manuscript', async () => {
      const testJournalRes = await apiClient.createJournal(
        createJournalPayload({ journal_name: 'Test Journal' }),
        journalEditorHeaders
      );
      const testJournal = handleApiResponse<Journal>(testJournalRes, 201);

      const manuscriptARes = await apiClient.createManuscript(
        testJournal.id,
        createManuscriptPayload({ title: 'Manuscript A' }),
        sectionEditorHeaders
      );
      const manuscriptA = handleApiResponse<Manuscript>(manuscriptARes, 201);

      const manuscriptBRes = await apiClient.createManuscript(
        testJournal.id,
        createManuscriptPayload({ title: 'Manuscript B' }),
        sectionEditorHeaders
      );
      const manuscriptB = handleApiResponse<Manuscript>(manuscriptBRes, 201);

      await apiClient.beginReview(testJournal.id, journalEditorHeaders);

      const assignmentRes = await apiClient.createReviewAssignment(
        testJournal.id,
        manuscriptB.id,
        createReviewAssignmentPayload({ required_expertise: 'Manuscript B Assignment' }),
        sectionEditorHeaders
      );
      const assignmentB = handleApiResponse<ReviewAssignment>(assignmentRes, 201);

      const res = await apiClient.getReviewAssignment(
        testJournal.id,
        manuscriptA.id,
        assignmentB.id,
        journalEditorHeaders
      );

      validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_ASSIGNMENT_NOT_FOUND });
    });

    it('should handle data isolation when getting an assignment from a different journal', async () => {
      const journalA = await setupJournal({ journal_name: 'Journal A' });
      const journalB = await setupJournal({ journal_name: 'Journal B' });

      const manuscriptBRes = await apiClient.createManuscript(
        journalB.id,
        createManuscriptPayload({ title: 'Manuscript B' }),
        sectionEditorHeaders
      );
      const manuscriptB = handleApiResponse<Manuscript>(manuscriptBRes, 201);

      await apiClient.beginReview(journalA.id, journalEditorHeaders);
      await apiClient.beginReview(journalB.id, journalEditorHeaders);

      const assignmentBRes = await apiClient.createReviewAssignment(
        journalB.id,
        manuscriptB.id,
        createReviewAssignmentPayload({ required_expertise: 'Manuscript B Assignment' }),
        sectionEditorHeaders
      );
      const assignmentB = handleApiResponse<ReviewAssignment>(assignmentBRes, 201);

      const res = await apiClient.getReviewAssignment(
        journalA.id,
        manuscriptB.id,
        assignmentB.id,
        journalEditorHeaders
      );

      validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_MANUSCRIPT_NOT_FOUND });
    });
  });

  describe('ReviewerProfile Resource', () => {
    it('should create a new Reviewer Profile', async () => {
      const journal = await setupJournal();

      const reviewerPayload = createReviewerProfilePayload({
        full_name: 'Dr. Jane Smith',
        institution: 'MIT',
        expertise_areas: ['Machine Learning', 'Computer Vision'],
      });

      const res = await apiClient.createReviewerProfile(
        journal.id,
        reviewerPayload,
        sectionEditorHeaders
      );
      const reviewerProfile = handleApiResponse<ReviewerProfile>(res, 201);

      assertReviewerProfile(reviewerProfile);
      expect(reviewerProfile.full_name).toBe('Dr. Jane Smith');
      expect(reviewerProfile.institution).toBe('MIT');
      expect(reviewerProfile.expertise_areas).toEqual(['Machine Learning', 'Computer Vision']);
      expect(reviewerProfile.journal_id).toBe(journal.id);
    });

    it('should not create a Reviewer Profile under a non-existent journal', async () => {
      const reviewerPayload = createReviewerProfilePayload();
      const res = await apiClient.createReviewerProfile(
        NON_EXISTENT_UUID,
        reviewerPayload,
        sectionEditorHeaders
      );
      validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_JOURNAL_NOT_FOUND });
    });

    it('should handle data isolation for a Reviewer Profile from a different journal', async () => {
      const journalA = await setupJournal({ journal_name: 'Journal A' });
      const journalB = await setupJournal({ journal_name: 'Journal B' });

      const reviewerRes = await apiClient.createReviewerProfile(
        journalB.id,
        createReviewerProfilePayload({
          full_name: 'Dr. Bob Johnson',
          institution: 'Stanford',
          expertise_areas: ['Deep Learning'],
        }),
        sectionEditorHeaders
      );
      const reviewerB = handleApiResponse<ReviewerProfile>(reviewerRes, 201);

      const res = await apiClient.getReviewerProfile(journalA.id, reviewerB.id, journalEditorHeaders);
      validateErrorEnvelope(res, {
        expectedErrorId: ApiErrorId.ERR_REVIEWER_NOT_FOUND,
      });
    });

    it('should not get a non-existent Reviewer Profile', async () => {
      const journal = await setupJournal();

      const res = await apiClient.getReviewerProfile(journal.id, NON_EXISTENT_UUID, journalEditorHeaders);
      validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_REVIEWER_NOT_FOUND });
    });

    it('should add a certification to a Reviewer Profile', async () => {
      const journal = await setupJournal();

      const reviewerRes = await apiClient.createReviewerProfile(
        journal.id,
        createReviewerProfilePayload({ full_name: 'Dr. Certified Expert' }),
        sectionEditorHeaders
      );
      const reviewer = handleApiResponse<ReviewerProfile>(reviewerRes, 201);

      const certificationPayload = createCertificationPayload(
        CertificationName.PhD,
        {
          granted_date: '2020-01-01',
        }
      );

      const res = await apiClient.addCertification(
        journal.id,
        reviewer.id,
        certificationPayload,
        sectionEditorHeaders
      );
      const certification = handleApiResponse<Certification>(res, 201);

      assertCertification(certification);
      expect(certification.name).toBe(CertificationName.PhD);
      expect(certification.granted_date).toBe('2020-01-01');
    });

    it('should not add a certification to a non-existent Reviewer Profile', async () => {
      const journal = await setupJournal();

      const certificationPayload = createCertificationPayload(CertificationName.MD);
      const res = await apiClient.addCertification(
        journal.id,
        NON_EXISTENT_UUID,
        certificationPayload,
        sectionEditorHeaders
      );
      validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_REVIEWER_NOT_FOUND });
    });
  });

  describe('Review Resource', () => {
    it('should not create a Review under a non-existent journal', async () => {
      const invitationPayload = createReviewInvitationPayload(
        NON_EXISTENT_UUID,
        NON_EXISTENT_UUID
      );
      const res = await apiClient.inviteReviewer(
        NON_EXISTENT_UUID,
        invitationPayload,
        sectionEditorHeaders
      );
      validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_JOURNAL_NOT_FOUND });
    });

    it('should not perform operations on a non-existent Review', async () => {
      const journal = await setupJournalInReview();

    });

    it('should handle data isolation when getting a Review from a different journal', async () => {
      const journalA = await setupJournal({ journal_name: 'Journal A' });
      const journalB = await setupJournal({ journal_name: 'Journal B' });

      const manuscriptRes = await apiClient.createManuscript(
        journalB.id,
        createManuscriptPayload(),
        sectionEditorHeaders
      );
      const manuscript = handleApiResponse<Manuscript>(manuscriptRes, 201);

      const reviewerRes = await apiClient.createReviewerProfile(
        journalB.id,
        createReviewerProfilePayload(),
        sectionEditorHeaders
      );
      const reviewer = handleApiResponse<ReviewerProfile>(reviewerRes, 201);

      await apiClient.beginReview(journalA.id, journalEditorHeaders);
      await apiClient.beginReview(journalB.id, journalEditorHeaders);

      const assignmentRes = await apiClient.createReviewAssignment(
        journalB.id,
        manuscript.id,
        createReviewAssignmentPayload(),
        sectionEditorHeaders
      );
      const assignment = handleApiResponse<ReviewAssignment>(assignmentRes, 201);

      const reviewRes = await apiClient.inviteReviewer(
        journalB.id,
        createReviewInvitationPayload(assignment.id, reviewer.id),
        sectionEditorHeaders
      );
      const reviewB = handleApiResponse<Review>(reviewRes, 201);

    });

    it('should handle data isolation when declining a review from a different journal', async () => {
      const journalA = await setupJournal({ journal_name: 'Journal A' });
      const journalB = await setupJournal({ journal_name: 'Journal B' });

      const manuscriptRes = await apiClient.createManuscript(
        journalB.id,
        createManuscriptPayload(),
        sectionEditorHeaders
      );
      const manuscript = handleApiResponse<Manuscript>(manuscriptRes, 201);

      const reviewerRes = await apiClient.createReviewerProfile(
        journalB.id,
        createReviewerProfilePayload(),
        sectionEditorHeaders
      );
      const reviewer = handleApiResponse<ReviewerProfile>(reviewerRes, 201);

      await apiClient.beginReview(journalA.id, journalEditorHeaders);
      await apiClient.beginReview(journalB.id, journalEditorHeaders);

      const assignmentRes = await apiClient.createReviewAssignment(
        journalB.id,
        manuscript.id,
        createReviewAssignmentPayload(),
        sectionEditorHeaders
      );
      const assignment = handleApiResponse<ReviewAssignment>(assignmentRes, 201);

      const reviewRes = await apiClient.inviteReviewer(
        journalB.id,
        createReviewInvitationPayload(assignment.id, reviewer.id),
        sectionEditorHeaders
      );
      const reviewB = handleApiResponse<Review>(reviewRes, 201);

    });
  });

  describe('ConflictOfInterest Resource', () => {
    it('should create a ConflictOfInterest', async () => {
      const journal = await setupJournal();

      const reviewer1Res = await apiClient.createReviewerProfile(
        journal.id,
        createReviewerProfilePayload({ full_name: 'Dr. Alice' }),
        sectionEditorHeaders
      );
      const reviewer1 = handleApiResponse<ReviewerProfile>(reviewer1Res, 201);

      const reviewer2Res = await apiClient.createReviewerProfile(
        journal.id,
        createReviewerProfilePayload({ full_name: 'Dr. Bob' }),
        sectionEditorHeaders
      );
      const reviewer2 = handleApiResponse<ReviewerProfile>(reviewer2Res, 201);

      const conflictPayload = createConflictOfInterestPayload(
        reviewer1.id,
        reviewer2.id,
        {
          conflict_type: ConflictOfInterestType.PRIOR_COLLABORATION,
          reason: 'Co-authored multiple papers together.'
        }
      );

      const res = await apiClient.createConflictOfInterest(
        journal.id,
        conflictPayload,
        journalEditorHeaders
      );
      const conflict = handleApiResponse<ConflictOfInterest>(res, 201);

      assertConflictOfInterest(conflict);
      expect(conflict.entity_1_id).toBe(reviewer1.id);
      expect(conflict.entity_2_id).toBe(reviewer2.id);
      expect(conflict.conflict_type).toBe(ConflictOfInterestType.PRIOR_COLLABORATION);
      expect(conflict.reason).toBe('Co-authored multiple papers together.');
    });

    it('should not create a ConflictOfInterest with the same reviewer', async () => {
      const journal = await setupJournal();

      const reviewer1Res = await apiClient.createReviewerProfile(
        journal.id,
        createReviewerProfilePayload({ full_name: 'Dr. Self' }),
        sectionEditorHeaders
      );
      const reviewer1 = handleApiResponse<ReviewerProfile>(reviewer1Res, 201);

      const conflictPayload = createConflictOfInterestPayload(
        reviewer1.id,
        reviewer1.id
      );

      const res = await apiClient.createConflictOfInterest(
        journal.id,
        conflictPayload,
        journalEditorHeaders
      );

      validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_SELF_CONFLICT });
    });

    it('should not create a ConflictOfInterest under a non-existent journal', async () => {
      const conflictPayload = createConflictOfInterestPayload(
        NON_EXISTENT_UUID,
        NON_EXISTENT_UUID,
        { reason: 'Test reason' }
      );
      const res = await apiClient.createConflictOfInterest(
        NON_EXISTENT_UUID,
        conflictPayload,
        journalEditorHeaders
      );
      validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_JOURNAL_NOT_FOUND });
    });

    it('should handle data isolation when getting a ConflictOfInterest from a different journal', async () => {
      const journalA = await setupJournal({ journal_name: 'Journal A' });
      const journalB = await setupJournal({ journal_name: 'Journal B' });

      const reviewer1Res = await apiClient.createReviewerProfile(
        journalB.id,
        createReviewerProfilePayload({ full_name: 'Reviewer One' }),
        sectionEditorHeaders
      );
      const reviewer1 = handleApiResponse<ReviewerProfile>(reviewer1Res, 201);

      const reviewer2Res = await apiClient.createReviewerProfile(
        journalB.id,
        createReviewerProfilePayload({ full_name: 'Reviewer Two' }),
        sectionEditorHeaders
      );
      const reviewer2 = handleApiResponse<ReviewerProfile>(reviewer2Res, 201);

      const conflictRes = await apiClient.createConflictOfInterest(
        journalB.id,
        createConflictOfInterestPayload(reviewer1.id, reviewer2.id),
        journalEditorHeaders
      );
      const conflictB = handleApiResponse<ConflictOfInterest>(conflictRes, 201);

    });

    it('should not get a non-existent ConflictOfInterest', async () => {
      const journal = await setupJournal();

    });
  });

  describe('Global Validations', () => {
    it('should handle User Context Header Validation', async () => {
      const res1 = await apiClient.getJournals({} as any);
      validateErrorEnvelope(res1, { expectedErrorId: ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER });

      const headers2 = { 'X-User-Role': UserRole.JournalEditor } as any;
      const res2 = await apiClient.getJournals(headers2);
      validateErrorEnvelope(res2, { expectedErrorId: ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER });

      const headers3 = { 'X-User-ID': 'je-1' } as any;
      const res3 = await apiClient.getJournals(headers3);
      validateErrorEnvelope(res3, { expectedErrorId: ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER });

      const invalidHeaders = {
        'X-User-ID': 'user-1',
        'X-User-Role': 'InvalidRole',
      } as any;
      const res4 = await apiClient.getJournals(invalidHeaders);
      validateErrorEnvelope(res4, { expectedErrorId: ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER });
    });
  });

});
