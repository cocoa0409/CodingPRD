import {
  apiClient,
  buildUserHeaders,
  handleApiResponse,
  validateApiResponseStructure,
  validateErrorEnvelope,
  assertGroomingDay,
  assertSessionBlock,
  assertGroomingJob,
  assertGroomerStation, createAndActivateGroomingDay,
  createSessionBlock,
  createGroomingJob,
  createGroomerStation, GroomingDay,
  SessionBlock,
  GroomingJob,
  GroomerStation,
  JobAssignment,
  GroomingDayStatus,
  SessionBlockStatus,
  UserRole,
  SpecialCapabilityName, ApiErrorId,
  generatePetId
} from '../../../test-helpers';

describe('Phase 1: Endpoint Validation', () => {
  const clinicManagerHeaders = buildUserHeaders('manager-1', UserRole.ClinicManager);
  const technicianHeaders = buildUserHeaders('technician-1', UserRole.GroomingTechnician);
  const billingAdminHeaders = buildUserHeaders('billing-1', UserRole.BillingAdmin);

  const NON_EXISTENT_UUID = '00000000-0000-0000-0000-000000000000';

  async function fetchAllGroomingDays(headers: Record<string, string>): Promise<GroomingDay[]> {
    let offset = 0;
    const all: GroomingDay[] = [];
    while (true) {
      const res = await apiClient.getGroomingDays(headers, { limit: 100, offset });
      const envelope = validateApiResponseStructure<GroomingDay[]>(res, { expectPaginated: true });
      all.push(...envelope.data);
      if (!envelope.meta.has_more) break;
      offset += envelope.meta.limit ?? 0;
    }
    return all;
  }

  describe('GroomingDay Resource', () => {
    it('should create a new Grooming Day', async () => {
      const payload = {
        schedule_name: 'Daily Pet Grooming Schedule 2024',
        total_supply_budget: 1500.00,
      };

      const res = await apiClient.createGroomingDay(payload as any, clinicManagerHeaders);
      const groomingDay = handleApiResponse<GroomingDay>(res, 201);

      assertGroomingDay(groomingDay);

      expect(groomingDay.schedule_name).toBe('Daily Pet Grooming Schedule 2024');
      expect(groomingDay.total_supply_budget).toBe(1500.00);
      expect(groomingDay.status).toBe(GroomingDayStatus.PLANNING);
      expect(groomingDay.supply_stock_balance).toBe(1500.00);
      expect(groomingDay.allergy_exposure_score).toBe(0);
    });

    it('should list all Grooming Days', async () => {
      const day1Payload = { schedule_name: 'Day 1', total_supply_budget: 1000.00 };
      const day2Payload = { schedule_name: 'Day 2', total_supply_budget: 1200.00 };

      const res1 = await apiClient.createGroomingDay(day1Payload, clinicManagerHeaders);
      const day1 = handleApiResponse<GroomingDay>(res1, 201);

      const res2 = await apiClient.createGroomingDay(day2Payload, clinicManagerHeaders);
      const day2 = handleApiResponse<GroomingDay>(res2, 201);

      const days = await fetchAllGroomingDays(clinicManagerHeaders);

      expect(days.length).toBeGreaterThanOrEqual(2);
      const dayIds = days.map(d => d.id);
      expect(dayIds).toContain(day1.id);
      expect(dayIds).toContain(day2.id);
    });

    describe('Pagination for Grooming Days', () => {
      beforeEach(async () => {
        await apiClient.createGroomingDay({ schedule_name: 'PagiDay 1', total_supply_budget: 1000.00 }, clinicManagerHeaders);
        await apiClient.createGroomingDay({ schedule_name: 'PagiDay 2', total_supply_budget: 1100.00 }, clinicManagerHeaders);
        await apiClient.createGroomingDay({ schedule_name: 'PagiDay 3', total_supply_budget: 1200.00 }, clinicManagerHeaders);
      });

      it('should respect the limit parameter', async () => {
        const listRes = await apiClient.getGroomingDays(clinicManagerHeaders, { limit: 2 });
        const days = handleApiResponse<GroomingDay[]>(listRes, 200, { expectPaginated: true });
        expect(days.length).toBe(2);
      });

      it('should respect the offset parameter', async () => {
        const fullListRes = await apiClient.getGroomingDays(clinicManagerHeaders, { limit: 100 });
        const fullList = handleApiResponse<GroomingDay[]>(fullListRes, 200, { expectPaginated: true });
        const secondDayId = fullList[1].id;

        const listRes = await apiClient.getGroomingDays(clinicManagerHeaders, { limit: 1, offset: 1 });
        const days = handleApiResponse<GroomingDay[]>(listRes, 200, { expectPaginated: true });

        expect(days.length).toBe(1);
        expect(days[0].id).toBe(secondDayId);
      });
    });

    it('should get a specific Grooming Day', async () => {
      const payload = { schedule_name: 'Test Day', total_supply_budget: 800.00 };
      const createRes = await apiClient.createGroomingDay(payload, clinicManagerHeaders);
      const createdDay = handleApiResponse<GroomingDay>(createRes, 201);

      const getRes = await apiClient.getGroomingDay(createdDay.id, clinicManagerHeaders);
      const retrievedDay = handleApiResponse<GroomingDay>(getRes, 200);

      assertGroomingDay(retrievedDay);
      expect(retrievedDay.id).toBe(createdDay.id);
      expect(retrievedDay.schedule_name).toBe('Test Day');
    });

    it('should not get a non-existent Grooming Day', async () => {
      const res1 = await apiClient.getGroomingDay(NON_EXISTENT_UUID, clinicManagerHeaders);
      validateErrorEnvelope(res1, { expectedErrorId: ApiErrorId.ERR_DAY_NOT_FOUND });

      const res2 = await apiClient.activateGroomingDay(NON_EXISTENT_UUID, clinicManagerHeaders);
      validateErrorEnvelope(res2, { expectedErrorId: ApiErrorId.ERR_DAY_NOT_FOUND });
    });
  });

  describe('SessionBlock Resource', () => {
    let testDay: GroomingDay;

    beforeEach(async () => {
      testDay = await createAndActivateGroomingDay('Block Test Day', 2000.00);
    });

    it('should create a SessionBlock under an existing GroomingDay', async () => {
      const payload = {
        name: 'Morning Grooming Session',
        start_time: 1672531200,
        end_time: 1672552800,
      };

      const res = await apiClient.createSessionBlock(testDay.id, payload, technicianHeaders);
      const block = handleApiResponse<SessionBlock>(res, 201);

      assertSessionBlock(block);
      expect(block.name).toBe('Morning Grooming Session');
      expect(block.grooming_day_id).toBe(testDay.id);
      expect(block.status).toBe(SessionBlockStatus.PLANNING);
    });

    it('should not perform operations on a non-existent GroomingDay', async () => {
      const payload = { name: 'Test Block', start_time: 1672531200, end_time: 1672552800 };
      const res1 = await apiClient.createSessionBlock(NON_EXISTENT_UUID, payload, technicianHeaders);
      validateErrorEnvelope(res1, { expectedErrorId: ApiErrorId.ERR_DAY_NOT_FOUND });

      const res2 = await apiClient.getSessionBlocks(NON_EXISTENT_UUID, clinicManagerHeaders);
      validateErrorEnvelope(res2, { expectedErrorId: ApiErrorId.ERR_DAY_NOT_FOUND });

      const blockRes = await apiClient.createSessionBlock(
        testDay.id,
        { name: 'Valid Block', start_time: 1672531200, end_time: 1672552800 },
        technicianHeaders
      );
      const block = handleApiResponse<SessionBlock>(blockRes, 201);

      const res3 = await apiClient.getSessionBlock(NON_EXISTENT_UUID, block.id, clinicManagerHeaders);
      validateErrorEnvelope(res3, { expectedErrorId: ApiErrorId.ERR_DAY_NOT_FOUND });
    });

    describe('Pagination for Session Blocks', () => {
      beforeEach(async () => {
        await apiClient.createSessionBlock(testDay.id, { name: 'Block A', start_time: 1672531200, end_time: 1672534800 }, technicianHeaders);
        await apiClient.createSessionBlock(testDay.id, { name: 'Block B', start_time: 1672538400, end_time: 1672542000 }, technicianHeaders);
        await apiClient.createSessionBlock(testDay.id, { name: 'Block C', start_time: 1672545600, end_time: 1672549200 }, technicianHeaders);
      });

      it('should respect the limit parameter for blocks', async () => {
        const listRes = await apiClient.getSessionBlocks(testDay.id, clinicManagerHeaders, { limit: 1 });
        const blocks = handleApiResponse<SessionBlock[]>(listRes, 200, { expectPaginated: true });
        expect(blocks.length).toBe(1);
      });

      it('should accept requests with limit=100', async () => {
        const res = await apiClient.getSessionBlocks(testDay.id, clinicManagerHeaders, { limit: 100 });

        expect(res.status).toBe(200);
        const blocks = handleApiResponse<SessionBlock[]>(res, 200, { expectPaginated: true });
        expect(blocks.length).toBeLessThanOrEqual(100);
      });

      it('should respect the offset parameter for blocks', async () => {
        const fullListRes = await apiClient.getSessionBlocks(testDay.id, clinicManagerHeaders);
        const fullList = handleApiResponse<SessionBlock[]>(fullListRes, 200, { expectPaginated: true });
        const secondBlockId = fullList[1].id;

        const listRes = await apiClient.getSessionBlocks(testDay.id, clinicManagerHeaders, { limit: 1, offset: 1 });
        const blocks = handleApiResponse<SessionBlock[]>(listRes, 200, { expectPaginated: true });

        expect(blocks.length).toBe(1);
        expect(blocks[0].id).toBe(secondBlockId);
      });
    });

    it('should get a specific existing SessionBlock', async () => {
      const blockPayload = { name: 'Test Block', start_time: 1672531200, end_time: 1672534800 };
      const createRes = await apiClient.createSessionBlock(testDay.id, blockPayload, technicianHeaders);
      const createdBlock = handleApiResponse<SessionBlock>(createRes, 201);

      const getRes = await apiClient.getSessionBlock(testDay.id, createdBlock.id, clinicManagerHeaders);
      const retrievedBlock = handleApiResponse<SessionBlock>(getRes, 200);

      assertSessionBlock(retrievedBlock);
      expect(retrievedBlock.id).toBe(createdBlock.id);
      expect(retrievedBlock.name).toBe('Test Block');
    });

    it('should not perform operations on a non-existent SessionBlock', async () => {
      const res1 = await apiClient.getSessionBlock(testDay.id, NON_EXISTENT_UUID, clinicManagerHeaders);
      validateErrorEnvelope(res1, { expectedErrorId: ApiErrorId.ERR_BLOCK_NOT_FOUND });

      const res2 = await apiClient.updateSessionBlockStatus(
        testDay.id,
        NON_EXISTENT_UUID,
        { status: SessionBlockStatus.READY_FOR_GROOMING },
        clinicManagerHeaders
      );
      validateErrorEnvelope(res2, { expectedErrorId: ApiErrorId.ERR_BLOCK_NOT_FOUND });
    });

    it('should handle data isolation for a SessionBlock from a different day', async () => {
      const dayA = await createAndActivateGroomingDay('Day A', 1500.00);
      const dayB = await createAndActivateGroomingDay('Day B', 1600.00);

      const blockRes = await apiClient.createSessionBlock(
        dayB.id,
        { name: 'Day B Block', start_time: 1672531200, end_time: 1672534800 },
        technicianHeaders
      );
      const blockB = handleApiResponse<SessionBlock>(blockRes, 201);

      const res = await apiClient.getSessionBlock(dayA.id, blockB.id, clinicManagerHeaders);
      validateErrorEnvelope(res, {
        expectedErrorId: ApiErrorId.ERR_BLOCK_NOT_FOUND,
      });
    });

    it('should handle data isolation when updating a SessionBlock from different day', async () => {
      const dayA = await createAndActivateGroomingDay('Day A', 1500.00);
      const dayB = await createAndActivateGroomingDay('Day B', 1600.00);

      const blockRes = await apiClient.createSessionBlock(
        dayB.id,
        { name: 'Day B Block', start_time: 1672531200, end_time: 1672534800 },
        technicianHeaders
      );
      const blockB = handleApiResponse<SessionBlock>(blockRes, 201);

      const res = await apiClient.updateSessionBlockStatus(
        dayA.id,
        blockB.id,
        { status: SessionBlockStatus.READY_FOR_GROOMING },
        clinicManagerHeaders
      );
      validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_BLOCK_NOT_FOUND });
    });
  });

  describe('GroomingJob Resource', () => {
    let groomingDay: GroomingDay;
    let sessionBlock: SessionBlock;

    beforeEach(async () => {
      groomingDay = await createAndActivateGroomingDay('Job Test Day', 2500.00);
      sessionBlock = await createSessionBlock(groomingDay.id, 'Test Block', 1, 4);
    });

    it('should not create a GroomingJob with invalid times', async () => {
      const jobPayload1 = {
        pet_id: generatePetId(1),
        job_type: 'Basic Grooming',
        start_time: 1672534800,
        end_time: 1672531200,
      };
      const res1 = await apiClient.createGroomingJob(
        groomingDay.id,
        sessionBlock.id,
        jobPayload1,
        technicianHeaders
      );
      validateErrorEnvelope(res1, { expectedErrorId: ApiErrorId.ERR_INVALID_JOB_TIMES });

      const now = 1672534800;
      const jobPayload2 = {
        pet_id: generatePetId(2),
        job_type: 'Quick Trim',
        start_time: now,
        end_time: now,
      };
      const res2 = await apiClient.createGroomingJob(
        groomingDay.id,
        sessionBlock.id,
        jobPayload2,
        technicianHeaders
      );
      validateErrorEnvelope(res2, { expectedErrorId: ApiErrorId.ERR_INVALID_JOB_TIMES });
    });

    it('should not create a GroomingJob under a non-existent SessionBlock', async () => {
      const jobPayload = {
        pet_id: generatePetId(3),
        job_type: 'Standard Grooming',
        start_time: 1672531200,
        end_time: 1672534800,
      };
      const res = await apiClient.createGroomingJob(
        groomingDay.id,
        NON_EXISTENT_UUID,
        jobPayload,
        technicianHeaders
      );
      validateErrorEnvelope(res, {
        expectedErrorId: ApiErrorId.ERR_BLOCK_NOT_FOUND
      });
    });

    it('should get a specific existing GroomingJob', async () => {
      const jobPayload = {
        pet_id: generatePetId(4),
        job_type: 'Flea Treatment',
        start_time: 1672531200,
        end_time: 1672534800,
      };
      const createRes = await apiClient.createGroomingJob(
        groomingDay.id,
        sessionBlock.id,
        jobPayload,
        technicianHeaders
      );
      const createdJob = handleApiResponse<GroomingJob>(createRes, 201);

      const getRes = await apiClient.getGroomingJob(
        groomingDay.id,
        sessionBlock.id,
        createdJob.id,
        clinicManagerHeaders
      );
      const retrievedJob = handleApiResponse<GroomingJob>(getRes, 200);

      assertGroomingJob(retrievedJob);
      expect(retrievedJob.id).toBe(createdJob.id);
      expect(retrievedJob.job_type).toBe('Flea Treatment');
    });

    it('should not get a non-existent GroomingJob', async () => {
      const res = await apiClient.getGroomingJob(
        groomingDay.id,
        sessionBlock.id,
        NON_EXISTENT_UUID,
        clinicManagerHeaders
      );
      validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_JOB_NOT_FOUND });
    });

    it('should handle data isolation when getting a job from the wrong block', async () => {
      const blockA = await createSessionBlock(groomingDay.id, 'Block A', 1, 2);
      const blockB = await createSessionBlock(groomingDay.id, 'Block B', 3, 2);

      const jobRes = await apiClient.createGroomingJob(
        groomingDay.id,
        blockB.id,
        {
          pet_id: generatePetId(5),
          job_type: 'Block B Job',
          start_time: 1672531200,
          end_time: 1672534800,
        },
        technicianHeaders
      );
      const jobB = handleApiResponse<GroomingJob>(jobRes, 201);

      const res = await apiClient.getGroomingJob(
        groomingDay.id,
        blockA.id,
        jobB.id,
        clinicManagerHeaders
      );

      validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_JOB_NOT_FOUND });
    });

    it('should handle data isolation when getting a job from a different day', async () => {
      const dayA = await createAndActivateGroomingDay('Day A', 1500.00);
      const dayB = await createAndActivateGroomingDay('Day B', 1600.00);

      const blockB = await createSessionBlock(dayB.id, 'Block B', 1, 2);
      const jobBRes = await apiClient.createGroomingJob(
        dayB.id,
        blockB.id,
        {
          pet_id: generatePetId(6),
          job_type: 'Day B Job',
          start_time: 1672531200,
          end_time: 1672534800,
        },
        technicianHeaders
      );
      const jobB = handleApiResponse<GroomingJob>(jobBRes, 201);

      const res = await apiClient.getGroomingJob(
        dayA.id,
        blockB.id,
        jobB.id,
        clinicManagerHeaders
      );

      validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_BLOCK_NOT_FOUND });
    });
  });

  describe('GroomerStation Resource', () => {
    it('should create a new GroomerStation', async () => {
      const groomingDay = await createAndActivateGroomingDay('Station Test Day', 1800.00);

      const stationPayload = {
        station_name: 'grooming-station-01',
        station_type: 'large-pets',
        supply_cost_per_hour: 25.50,
      };

      const res = await apiClient.createGroomerStation(
        groomingDay.id,
        stationPayload,
        technicianHeaders
      );
      const station = handleApiResponse<GroomerStation>(res, 201);

      assertGroomerStation(station);
      expect(station.station_name).toBe('grooming-station-01');
      expect(station.station_type).toBe('large-pets');
      expect(station.supply_cost_per_hour).toBe(25.50);
      expect(station.grooming_day_id).toBe(groomingDay.id);
    });

    it('should not create a GroomerStation under a non-existent day', async () => {
      const stationPayload = {
        station_name: 'test-station',
        station_type: 'standard',
        supply_cost_per_hour: 20.00,
      };
      const res = await apiClient.createGroomerStation(
        NON_EXISTENT_UUID,
        stationPayload,
        technicianHeaders
      );
      validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_DAY_NOT_FOUND });
    });

    it('should handle data isolation for a GroomerStation from a different day', async () => {
      const dayA = await createAndActivateGroomingDay('Day A', 1500.00);
      const dayB = await createAndActivateGroomingDay('Day B', 1600.00);

      const stationRes = await apiClient.createGroomerStation(
        dayB.id,
        {
          station_name: 'day-b-station',
          station_type: 'deluxe',
          supply_cost_per_hour: 35.00,
        },
        technicianHeaders
      );
      const stationB = handleApiResponse<GroomerStation>(stationRes, 201);

      const res = await apiClient.getGroomerStation(dayA.id, stationB.id, clinicManagerHeaders);
      validateErrorEnvelope(res, {
        expectedErrorId: ApiErrorId.ERR_STATION_NOT_FOUND,
      });
    });

    it('should not get a non-existent GroomerStation', async () => {
      const groomingDay = await createAndActivateGroomingDay('Test Day', 1000.00);

      const res = await apiClient.getGroomerStation(groomingDay.id, NON_EXISTENT_UUID, clinicManagerHeaders);
      validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_STATION_NOT_FOUND });
    });

    it('should add a special capability to a GroomerStation', async () => {
      const groomingDay = await createAndActivateGroomingDay('Capability Test Day', 1500.00);

      const stationRes = await apiClient.createGroomerStation(
        groomingDay.id,
        { station_name: 'allergy-safe-station', station_type: 'hypoallergenic', supply_cost_per_hour: 30.00 },
        technicianHeaders
      );
      const station = handleApiResponse<GroomerStation>(stationRes, 201);

      const capabilityPayload = {
        name: SpecialCapabilityName.NUT_ALLERGY_SAFE,
        enabled_date: '2023-01-01',
      };

      const res = await apiClient.addSpecialCapability(
        groomingDay.id,
        station.id,
        capabilityPayload,
        technicianHeaders
      );
      const updatedStation = handleApiResponse<GroomerStation>(res, 201);

      assertGroomerStation(updatedStation);
      expect(updatedStation.special_capabilities.length).toBe(1);
      expect(updatedStation.special_capabilities[0].name).toBe(SpecialCapabilityName.NUT_ALLERGY_SAFE);
    });

    it('should not add a special capability to a non-existent GroomerStation', async () => {
      const groomingDay = await createAndActivateGroomingDay('Test Day', 1000.00);

      const capabilityPayload = {
        name: SpecialCapabilityName.GRASS_ALLERGY_SAFE,
        enabled_date: '2023-01-01',
      };
      const res = await apiClient.addSpecialCapability(
        groomingDay.id,
        NON_EXISTENT_UUID,
        capabilityPayload,
        technicianHeaders
      );
      validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_STATION_NOT_FOUND });
    });
  });

  describe('JobAssignment Resource', () => {
    it('should not create a JobAssignment under a non-existent day', async () => {
      const assignmentPayload = {
        job_id: NON_EXISTENT_UUID,
        station_id: NON_EXISTENT_UUID,
      };
      const res = await apiClient.createJobAssignment(
        NON_EXISTENT_UUID,
        assignmentPayload,
        technicianHeaders
      );
      validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_DAY_NOT_FOUND });
    });

    it('should not perform operations on a non-existent JobAssignment', async () => {
      const groomingDay = await createAndActivateGroomingDay('Assignment Test Day', 2000.00);

      const res1 = await apiClient.getJobAssignment(groomingDay.id, NON_EXISTENT_UUID, clinicManagerHeaders);
      validateErrorEnvelope(res1, { expectedErrorId: ApiErrorId.ERR_ASSIGNMENT_NOT_FOUND });

      const res2 = await apiClient.confirmJobAssignment(
        groomingDay.id,
        NON_EXISTENT_UUID,
        clinicManagerHeaders
      );
      validateErrorEnvelope(res2, { expectedErrorId: ApiErrorId.ERR_ASSIGNMENT_NOT_FOUND });

      const res3 = await apiClient.terminateJobAssignment(
        groomingDay.id,
        NON_EXISTENT_UUID,
        clinicManagerHeaders
      );
      validateErrorEnvelope(res3, { expectedErrorId: ApiErrorId.ERR_ASSIGNMENT_NOT_FOUND });
    });

    it('should handle data isolation when getting a JobAssignment from a different day', async () => {
      const dayA = await createAndActivateGroomingDay('Day A', 1500.00);
      const dayB = await createAndActivateGroomingDay('Day B', 1600.00);

      const blockB = await createSessionBlock(dayB.id, 'Block B', 1, 3);
      const jobB = await createGroomingJob(
        dayB.id,
        blockB.id,
        generatePetId(10),
        'Basic Grooming',
        1,
        60
      );
      const stationB = await createGroomerStation(
        dayB.id,
        'station-b',
        'standard',
        20.00
      );

      const assignmentRes = await apiClient.createJobAssignment(
        dayB.id,
        { job_id: jobB.id, station_id: stationB.id },
        technicianHeaders
      );
      const assignmentB = handleApiResponse<JobAssignment>(assignmentRes, 201);

      const res = await apiClient.getJobAssignment(
        dayA.id,
        assignmentB.id,
        clinicManagerHeaders
      );
      validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_ASSIGNMENT_NOT_FOUND });
    });

    it('should handle data isolation when terminating an assignment from a different day', async () => {
      const dayA = await createAndActivateGroomingDay('Day A', 1500.00);
      const dayB = await createAndActivateGroomingDay('Day B', 1600.00);

      const blockB = await createSessionBlock(dayB.id, 'Block B', 1, 3);
      const jobB = await createGroomingJob(
        dayB.id,
        blockB.id,
        generatePetId(11),
        'Nail Trim',
        1,
        30
      );
      const stationB = await createGroomerStation(
        dayB.id,
        'station-b',
        'standard',
        15.00
      );

      const assignmentRes = await apiClient.createJobAssignment(
        dayB.id,
        { job_id: jobB.id, station_id: stationB.id },
        technicianHeaders
      );
      const assignmentB = handleApiResponse<JobAssignment>(assignmentRes, 201);

      const res = await apiClient.terminateJobAssignment(
        dayA.id,
        assignmentB.id,
        clinicManagerHeaders
      );

      validateErrorEnvelope(res, {
        expectedErrorId: ApiErrorId.ERR_ASSIGNMENT_NOT_FOUND,
      });
    });
  });

  describe('Global Validations', () => {
    it('should handle User Context Header Validation', async () => {
      const res1 = await apiClient.getGroomingDays({});
      validateErrorEnvelope(res1, { expectedErrorId: ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER });

      const headers2 = { 'X-User-Role': UserRole.ClinicManager };
      const res2 = await apiClient.getGroomingDays(headers2);
      validateErrorEnvelope(res2, { expectedErrorId: ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER });

      const headers3 = { 'X-User-ID': 'manager-1' };
      const res3 = await apiClient.getGroomingDays(headers3);
      validateErrorEnvelope(res3, { expectedErrorId: ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER });

      const invalidHeaders = {
        'X-User-ID': 'user-1',
        'X-User-Role': 'InvalidRole',
      };
      const res4 = await apiClient.getGroomingDays(invalidHeaders);
      validateErrorEnvelope(res4, { expectedErrorId: ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER });
    });
  });

  describe('Invalid grooming day creation requests', () => {
    it('should return ERR_INVALID_REQUEST when schedule_name or total_supply_budget is missing', async () => {
      const payload = { total_supply_budget: 1000.00 };
      delete (payload as any).schedule_name;

      const res = await apiClient.createGroomingDay(payload as any, clinicManagerHeaders);

      validateErrorEnvelope(res, {
        expectedErrorId: ApiErrorId.ERR_INVALID_REQUEST,
      });

      const payload2 = { schedule_name: 'Test Day' };
      delete (payload as any).total_supply_budget;

      const res2 = await apiClient.createGroomingDay(payload2 as any, clinicManagerHeaders);

      validateErrorEnvelope(res, {
        expectedErrorId: ApiErrorId.ERR_INVALID_REQUEST,
      });
    });
  });
});
