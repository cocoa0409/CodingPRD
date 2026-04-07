import {
  apiClient,
  buildUserHeaders,
  handleApiResponse,
  validateErrorEnvelope,
  createAndActivateGroomingDay,
  createSessionBlock,
  createGroomingJob,
  createGroomerStation,
  createJobAssignment,
  confirmJobAssignment, createPeakSessionAssignments, GroomingDay,
  SessionBlock,
  GroomingJob,
  GroomerStation,
  JobAssignment,
  SessionBlockStatus,
  UserRole,
  ApiErrorId,
  JobAssignmentStatus,
  RequiredAllergenType, createUnixTimestamp,
  addHours, SYSTEM_CONSTANTS
} from '../../../test-helpers';

describe('Phase 4: Edge Cases', () => {
  const managerHeaders = buildUserHeaders('manager-1', UserRole.ClinicManager);
  const techHeaders = buildUserHeaders('tech-1', UserRole.GroomingTechnician);
  const billingHeaders = buildUserHeaders('billing-1', UserRole.BillingAdmin);

  it('should default required_allergen_type to NONE when omitted and allow assignment', async () => {
    const day = await createAndActivateGroomingDay('Edge Case Day', 5000.00);
    const block = await createSessionBlock(day.id, 'Test Block', 1, 4);
    const station = await createGroomerStation(day.id, 'Station-1', 'Standard', 10.00);

    const jobPayload = {
      pet_id: 'pet-001',
      job_type: 'DefaultAllergenTask',
      start_time: createUnixTimestamp(2),
      end_time: addHours(createUnixTimestamp(2), 1),
    };

    const jobRes = await apiClient.createGroomingJob(day.id, block.id, jobPayload, techHeaders);
    const job = handleApiResponse<GroomingJob>(jobRes, 201);

    expect(job.required_allergen_type).toBe(RequiredAllergenType.NONE);

    const assignmentRes = await apiClient.createJobAssignment(
      day.id,
      {
        job_id: job.id,
        station_id: station.id,
      },
      techHeaders
    );
    const assignment = handleApiResponse<JobAssignment>(assignmentRes, 201);

    expect(assignment.job_id).toBe(job.id);
    expect(assignment.station_id).toBe(station.id);
  });

  it('should not alter allergy score if override was flagged but not actually used', async () => {
    const day = await createAndActivateGroomingDay('Override Test Day', 5000.00);
    const block = await createSessionBlock(day.id, 'Test Block', 1, 4);
    const station = await createGroomerStation(day.id, 'Station-1', 'Standard', 10.00);
    const job = await createGroomingJob(day.id, block.id, 'pet-001', 'Basic Grooming', 2, 60);

    const assignmentRes = await apiClient.createJobAssignment(
      day.id,
      {
        job_id: job.id,
        station_id: station.id,
        override_allergy_check: true,
      },
      techHeaders
    );
    const assignment = handleApiResponse<JobAssignment>(assignmentRes, 201);

    expect(assignment.allergy_override_penalty_applied).toBe(false);
    const dayState1 = await apiClient.getGroomingDay(day.id, managerHeaders).then(res => handleApiResponse<GroomingDay>(res, 200));
    expect(dayState1.allergy_exposure_score).toBe(0);

    await apiClient.terminateJobAssignment(day.id, assignment.id, managerHeaders);

    const dayState2 = await apiClient.getGroomingDay(day.id, managerHeaders).then(res => handleApiResponse<GroomingDay>(res, 200));
    expect(dayState2.allergy_exposure_score).toBe(0);
  });

  describe('Job Assignment mutations are day-isolated', () => {
    let dayA: GroomingDay;
    let dayB: GroomingDay;
    let assignmentInA: JobAssignment;

    beforeEach(async () => {
      dayA = await createAndActivateGroomingDay('Day A', 5000.00);
      dayB = await createAndActivateGroomingDay('Day B', 5000.00);
      const blockA = await createSessionBlock(dayA.id, 'Block A', 1, 4);
      const stationInA = await createGroomerStation(dayA.id, 'Station-A', 'Standard', 10.00);
      const jobInA = await createGroomingJob(dayA.id, blockA.id, 'pet-001', 'Basic Grooming', 2, 60);

      const assignmentRes = await apiClient.createJobAssignment(dayA.id, { job_id: jobInA.id, station_id: stationInA.id }, techHeaders);
      assignmentInA = handleApiResponse<JobAssignment>(assignmentRes, 201);
    });

    it('should fail to CONFIRM a job assignment via the wrong day path', async () => {
      const confirmRes = await apiClient.confirmJobAssignment(dayB.id, assignmentInA.id, managerHeaders);

      validateErrorEnvelope(confirmRes, { expectedErrorId: ApiErrorId.ERR_ASSIGNMENT_NOT_FOUND });
    });

    it('should fail to TERMINATE a job assignment via the wrong day path', async () => {
      const terminateRes = await apiClient.terminateJobAssignment(dayB.id, assignmentInA.id, managerHeaders);

      validateErrorEnvelope(terminateRes, { expectedErrorId: ApiErrorId.ERR_ASSIGNMENT_NOT_FOUND });
    });
  });

  it('should correctly calculate provisional cost at assignment without double-counting its own duration', async () => {
    const day = await createAndActivateGroomingDay('Cost Calculation Day', 5000.00);
    const block = await createSessionBlock(day.id, 'Cost Block', 1, 8);
    const station = await createGroomerStation(day.id, 'Cost Station', 'Standard', 20.00);

    await createPeakSessionAssignments(day.id, block.id, station.id, 5, 24);

    const dayAfterBase = await apiClient.getGroomingDay(day.id, managerHeaders).then(res => handleApiResponse<GroomingDay>(res, 200));
    expect(dayAfterBase.supply_stock_balance).toBeLessThan(5000.00);

    const peakJob = await createGroomingJob(
      day.id, block.id,
      'pet-peak-001',
      'Peak Grooming',
      120,
      20,
    );

    const peakAssignmentProposal = await createJobAssignment(day.id, peakJob.id, station.id);

    const expectedProvisionalCost = (20 / 60) * 20.00 * SYSTEM_CONSTANTS.PEAK_RATE_MULTIPLIER;
    expect(peakAssignmentProposal.is_peak_session).toBe(true);
    expect(peakAssignmentProposal.provisional_supply_cost).toBeCloseTo(expectedProvisionalCost);

    const confirmedAssignment = await confirmJobAssignment(day.id, peakAssignmentProposal.id);

    expect(confirmedAssignment.status).toBe(JobAssignmentStatus.CONFIRMED);
    expect(confirmedAssignment.provisional_supply_cost).toBeCloseTo(expectedProvisionalCost);
    expect(confirmedAssignment.is_peak_session).toBe(true);

    const dayAfterConfirm = await apiClient.getGroomingDay(day.id, managerHeaders).then(res => handleApiResponse<GroomingDay>(res, 200));
    const expectedBudgetDecrease = expectedProvisionalCost;
    expect(dayAfterConfirm.supply_stock_balance).toBeLessThan(dayAfterBase.supply_stock_balance);
  });

  it('should correctly credit budget on termination and prevent multiple terminations', async () => {
    const day = await createAndActivateGroomingDay('Termination Test Day', 1000.00);
    const block = await createSessionBlock(day.id, 'Test Block', 1, 4);
    const station = await createGroomerStation(day.id, 'Test Station', 'Standard', 20.00);
    const job = await createGroomingJob(
      day.id, block.id,
      'pet-term-001',
      'Termination Test Job',
      24,
      5 * 60,
    );

    const assignment = await createJobAssignment(day.id, job.id, station.id);
    const cost = (5 * 20.00);

    const dayState1 = await apiClient.getGroomingDay(day.id, managerHeaders).then(res => handleApiResponse<GroomingDay>(res, 200));
    expect(dayState1.supply_stock_balance).toBe(1000.00 - cost);

    await apiClient.terminateJobAssignment(day.id, assignment.id, managerHeaders);
    const dayState2 = await apiClient.getGroomingDay(day.id, managerHeaders).then(res => handleApiResponse<GroomingDay>(res, 200));
    expect(dayState2.supply_stock_balance).toBe(1000.00);

    const terminateAgainRes = await apiClient.terminateJobAssignment(day.id, assignment.id, managerHeaders);
    validateErrorEnvelope(terminateAgainRes, { expectedErrorId: ApiErrorId.ERR_ASSIGNMENT_NOT_TERMINABLE });

    const finalDayState = await apiClient.getGroomingDay(day.id, managerHeaders).then(res => handleApiResponse<GroomingDay>(res, 200));
    expect(finalDayState.supply_stock_balance).toBe(1000.00);
  });

  it('should succeed when assignment cost exactly matches remaining budget', async () => {
    const day = await createAndActivateGroomingDay('Exact Budget Day', 100.00);
    const block = await createSessionBlock(day.id, 'Exact Block', 1, 4);
    const station = await createGroomerStation(day.id, 'Exact Station', 'Standard', 20.00);
    const job = await createGroomingJob(
      day.id, block.id,
      'pet-exact-001',
      'Exact Budget Job',
      1,
      5 * 60,
    );

    const assignmentRes = await apiClient.createJobAssignment(
      day.id,
      { job_id: job.id, station_id: station.id },
      techHeaders
    );
    const assignment = handleApiResponse<JobAssignment>(assignmentRes, 201);

    expect(assignment.provisional_supply_cost).toBeCloseTo(100.00);

    const dayCheck = await apiClient.getGroomingDay(day.id, managerHeaders).then(res => handleApiResponse<GroomingDay>(res, 200));
    expect(dayCheck.supply_stock_balance).toBeCloseTo(0.00);
  });

  it('should fail when assignment cost exceeds budget by one cent', async () => {
    const day = await createAndActivateGroomingDay('Insufficient Budget Day', 99.99);
    const block = await createSessionBlock(day.id, 'Insufficient Block', 1, 4);
    const station = await createGroomerStation(day.id, 'Insufficient Station', 'Standard', 20.00);
    const job = await createGroomingJob(
      day.id, block.id,
      'pet-insufficient-001',
      'Expensive Job',
      1,
      5 * 60,
    );

    const assignmentRes = await apiClient.createJobAssignment(
      day.id,
      { job_id: job.id, station_id: station.id },
      techHeaders
    );

    validateErrorEnvelope(assignmentRes, { expectedErrorId: ApiErrorId.ERR_INSUFFICIENT_SUPPLIES });
  });

  it('should fail if cost exceeds budget due to peak session pricing', async () => {
    const day = await createAndActivateGroomingDay('Peak Budget Day', 519.99);
    const block = await createSessionBlock(day.id, 'Peak Block', 1, 200);

    const stations: GroomerStation[] = [];
    for (let i = 0; i < 6; i++) {
      const station = await createGroomerStation(day.id, `Station-${i + 1}`, 'Standard', 20.00);
      stations.push(station);
    }

    for (let i = 0; i < 5; i++) {
      const job = await createGroomingJob(
        day.id, block.id,
        `pet-base-${i + 1}`,
        `Base Job ${i + 1}`,
        i * 10,
        4 * 60,
      );
      const assignment = await createJobAssignment(day.id, job.id, stations[i].id);
      await confirmJobAssignment(day.id, assignment.id);
    }

    const jobPeak = await createGroomingJob(
      day.id, block.id,
      'pet-peak-001',
      'Peak Job',
      60,
      4 * 60,
    );

    const assignmentPeakRes = await apiClient.createJobAssignment(
      day.id,
      { job_id: jobPeak.id, station_id: stations[5].id },
      techHeaders
    );

    validateErrorEnvelope(assignmentPeakRes, { expectedErrorId: ApiErrorId.ERR_INSUFFICIENT_SUPPLIES });

    const dayCheck = await apiClient.getGroomingDay(day.id, managerHeaders).then(res => handleApiResponse<GroomingDay>(res, 200));
    expect(dayCheck.supply_stock_balance).toBeCloseTo(119.99);
  });

  it('should allow new assignment after budget is freed by termination', async () => {
    const day = await createAndActivateGroomingDay('Budget Recovery Day', 100.00);
    const block = await createSessionBlock(day.id, 'Recovery Block', 1, 4);
    const station = await createGroomerStation(day.id, 'Recovery Station', 'Standard', 20.00);

    const jobA = await createGroomingJob(
      day.id, block.id,
      'pet-first-001',
      'First Job',
      1,
      5 * 60,
    );
    const assignmentA = await createJobAssignment(day.id, jobA.id, station.id);

    const jobB = await createGroomingJob(
      day.id, block.id,
      'pet-second-001',
      'Second Job',
      24,
      5 * 60,
    );

    await apiClient.terminateJobAssignment(day.id, assignmentA.id, managerHeaders);

    const assignmentBRes = await apiClient.createJobAssignment(
      day.id,
      { job_id: jobB.id, station_id: station.id },
      techHeaders
    );
    const assignmentB = handleApiResponse<JobAssignment>(assignmentBRes, 201);

    expect(assignmentB.provisional_supply_cost).toBeCloseTo(100.00);
    const dayCheck = await apiClient.getGroomingDay(day.id, managerHeaders).then(res => handleApiResponse<GroomingDay>(res, 200));
    expect(dayCheck.supply_stock_balance).toBeCloseTo(0.00);
  });

  it('should terminate all assignments and revert all ledgers when block is cancelled', async () => {
    const day = await createAndActivateGroomingDay('Cascade Cancellation Day', 5000.00);

    const blockRes = await apiClient.createSessionBlock(
      day.id,
      { name: 'Cancellation Cascade Block', start_time: createUnixTimestamp(24), end_time: addHours(createUnixTimestamp(24), 8) },
      techHeaders
    );
    const block = handleApiResponse<SessionBlock>(blockRes, 201);

    const station1 = await createGroomerStation(day.id, 'Station-1', 'Standard', 10.00);
    const station2 = await createGroomerStation(day.id, 'Station-2', 'Premium', 20.00);

    const baseTime = createUnixTimestamp(24);
    const job1 = await createGroomingJob(day.id, block.id, 'pet-001', 'Job-1', 24, 10 * 60);
    const job2 = await createGroomingJob(day.id, block.id, 'pet-002', 'Job-2', 25, 10 * 60);
    const job3 = await createGroomingJob(day.id, block.id, 'pet-003', 'Job-3-Peak', 36, 60);

    const assignment1 = await createJobAssignment(day.id, job1.id, station1.id);

    const assignment2 = await createJobAssignment(day.id, job2.id, station2.id);

    const assignment3 = await createJobAssignment(day.id, job3.id, station2.id);
    await confirmJobAssignment(day.id, assignment3.id);

    const dayCheck1 = await apiClient.getGroomingDay(day.id, managerHeaders).then(res => handleApiResponse<GroomingDay>(res, 200));
    expect(dayCheck1.allergy_exposure_score).toBe(0);
    expect(dayCheck1.supply_stock_balance).toBeLessThan(5000.00);

    const blockCancelRes = await apiClient.updateSessionBlockStatus(
      day.id,
      block.id,
      { status: SessionBlockStatus.CANCELLED },
      managerHeaders
    );
    const cancelledBlock = handleApiResponse<SessionBlock>(blockCancelRes, 200);
    expect(cancelledBlock.status).toBe(SessionBlockStatus.CANCELLED);

    const finalAssignments = await apiClient.getJobAssignments(day.id, managerHeaders).then(res => handleApiResponse<JobAssignment[]>(res, 200, { expectPaginated: true }));
    expect(finalAssignments.find(a => a.id === assignment1.id)?.status).toBe(JobAssignmentStatus.TERMINATED);
    expect(finalAssignments.find(a => a.id === assignment2.id)?.status).toBe(JobAssignmentStatus.TERMINATED);
    expect(finalAssignments.find(a => a.id === assignment3.id)?.status).toBe(JobAssignmentStatus.TERMINATED);

    const dayCheck2 = await apiClient.getGroomingDay(day.id, managerHeaders).then(res => handleApiResponse<GroomingDay>(res, 200));
    expect(dayCheck2.allergy_exposure_score).toBe(0);
    expect(dayCheck2.supply_stock_balance).toBe(5000.00);
  });

  it('should correctly calculate peak session for an assignment that crosses the 5-job threshold when including its own count', async () => {
    const day = await createAndActivateGroomingDay('Peak Threshold Day', 50000.00);
    const blockRes = await apiClient.createSessionBlock(
      day.id,
      { name: 'Peak Threshold Block', start_time: createUnixTimestamp(0), end_time: addHours(createUnixTimestamp(0), 24) },
      techHeaders
    );
    const block = handleApiResponse<SessionBlock>(blockRes, 201);

    const stations: GroomerStation[] = [];
    for (let i = 0; i < 5; i++) {
      const station = await createGroomerStation(day.id, `Peak Station ${i + 1}`, 'Standard', 10.00);
      stations.push(station);
    }

    for (let i = 1; i <= 4; i++) {
      const job = await createGroomingJob(
        day.id, block.id,
        `pet-${String(i).padStart(3, '0')}`,
        `Job ${i}`,
        i,
        60,
      );
      const assignment = await createJobAssignment(day.id, job.id, stations[i - 1].id);
      await confirmJobAssignment(day.id, assignment.id);
    }

    const job5 = await createGroomingJob(
      day.id, block.id,
      'pet-005',
      'Fifth Job',
      6,
      60,
    );

    const assignment5Res = await apiClient.createJobAssignment(
      day.id,
      { job_id: job5.id, station_id: stations[4].id },
      techHeaders
    );
    const assignment5 = handleApiResponse<JobAssignment>(assignment5Res, 201);

    const confirmedAssignment = await confirmJobAssignment(day.id, assignment5.id);

    expect(confirmedAssignment.is_peak_session).toBe(false);
    expect(confirmedAssignment.provisional_supply_cost).toBe(1 * 10.00);
  });

  it('should correctly identify the 5th assignment as non-peak and 6th as peak', async () => {
    const day = await createAndActivateGroomingDay('Peak Boundary Test Day', 10000.00);
    const block = await createSessionBlock(day.id, 'Peak Boundary Block', 1, 200);

    const stations: GroomerStation[] = [];
    for (let i = 0; i < 6; i++) {
      const station = await createGroomerStation(day.id, `Station-${i + 1}`, 'Standard', 10.00);
      stations.push(station);
    }

    for (let i = 0; i < 4; i++) {
      const job = await createGroomingJob(
        day.id, block.id,
        `pet-${i + 1}`,
        `Job ${i + 1}`,
        i * 5,
        30,
      );
      const assignment = await createJobAssignment(day.id, job.id, stations[i].id);
      await confirmJobAssignment(day.id, assignment.id);
    }

    const job5 = await createGroomingJob(day.id, block.id, 'pet-5', 'Job 5', 25, 30);
    const assignment5 = await createJobAssignment(day.id, job5.id, stations[4].id);
    expect(assignment5.is_peak_session).toBe(false);
    await confirmJobAssignment(day.id, assignment5.id);

    const job6 = await createGroomingJob(day.id, block.id, 'pet-6', 'Job 6', 30, 30);
    const assignment6 = await createJobAssignment(day.id, job6.id, stations[5].id);
    expect(assignment6.is_peak_session).toBe(true);
    expect(assignment6.provisional_supply_cost).toBeCloseTo(0.5 * 10.00 * 1.5);
  });

});
